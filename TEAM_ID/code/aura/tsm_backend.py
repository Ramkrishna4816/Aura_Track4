"""Optional inference backend for the published EPIC-KITCHENS-100 RGB TSM.

The model specification is from the University of Bristol implementation at
e8e1a791944305c33adef09a966c51c0dfef0d38 and the temporal shift operation is
from Lin, Gan and Han (ICCV 2019). This implementation uses torchvision's
ResNet-50 and does not depend on the original training stack.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from pickle import UnpicklingError
from types import ModuleType
from typing import TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

if TYPE_CHECKING:
    import torch

TSM_SEGMENTS = 8
TSM_VERB_COUNT = 97
TSM_NOUN_COUNT = 300
_TSM_OUTPUTS = TSM_VERB_COUNT + TSM_NOUN_COUNT
_SHIFT_DIVISION = 8
_RESIZE_SHORT_SIDE = 256
_CROP_SIZE = 224
_MAX_BATCH_CLIPS = 2
# The published RGB checkpoint uses the same values for the two operations.
_RGB_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_RGB_STD = _RGB_MEAN.copy()


class TsmModelError(RuntimeError):
    """The optional TSM runtime, model weights, or scores were invalid."""


def _prepare_rgb_frame(frame: NDArray[np.uint8]) -> NDArray[np.float32]:
    """Match the original RGB test transform with a shorter-edge PIL resize."""
    from PIL import Image

    if frame.ndim != 3 or frame.shape[2] != 3 or not frame.size or frame.dtype != np.uint8:
        raise ValueError("TSM expects nonempty H×W×3 RGB uint8 frames")

    height, width = frame.shape[:2]
    if width < height:
        resized = (_RESIZE_SHORT_SIDE, _RESIZE_SHORT_SIDE * height // width)
    else:
        resized = (_RESIZE_SHORT_SIDE * width // height, _RESIZE_SHORT_SIDE)
    image = Image.fromarray(frame).resize(resized, Image.Resampling.BILINEAR)
    left, top = (round((side - _CROP_SIZE) / 2) for side in resized)
    crop = image.crop((left, top, left + _CROP_SIZE, top + _CROP_SIZE))
    pixels = np.asarray(crop, dtype=np.float32) / 255.0
    return ((pixels - _RGB_MEAN) / _RGB_STD).transpose(2, 0, 1)


def _shift_segments(frames: torch.Tensor) -> torch.Tensor:
    """Exchange channel subsets with neighboring frames inside each clip."""
    clips = frames.reshape(-1, TSM_SEGMENTS, *frames.shape[1:])
    channels = clips.shape[2] // _SHIFT_DIVISION
    shifted = clips.clone()
    forward = shifted[:, :, :channels]
    forward[:, :-1].copy_(clips[:, 1:, :channels])
    forward[:, -1].zero_()
    backward = shifted[:, :, channels:2 * channels]
    backward[:, 1:].copy_(clips[:, :-1, channels:2 * channels])
    backward[:, 0].zero_()
    return shifted.reshape_as(frames)


def _build_network(torch_runtime: ModuleType) -> torch.nn.Module:
    from torchvision.models import resnet50

    nn = torch_runtime.nn

    class ShiftedConvolution(nn.Module):
        def __init__(self, convolution: torch.nn.Conv2d) -> None:
            super().__init__()
            # Preserve the parameter path in the published RGB checkpoint.
            self.net = convolution

        def forward(self, frames: torch.Tensor) -> torch.Tensor:
            return self.net(_shift_segments(frames))

    class RgbTsm(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.base_model = resnet50(weights=None)
            channels = self.base_model.fc.in_features
            self.base_model.fc = nn.Dropout(p=0.7)
            for stage in (self.base_model.layer1, self.base_model.layer2,
                          self.base_model.layer3, self.base_model.layer4):
                for block in stage:
                    block.conv1 = ShiftedConvolution(block.conv1)
            self.new_fc = nn.Linear(channels, _TSM_OUTPUTS)

        def forward(self, clips: torch.Tensor) -> torch.Tensor:
            frame_features = self.base_model(clips.flatten(0, 1))
            frame_logits = self.new_fc(frame_features)
            return frame_logits.reshape(len(clips), TSM_SEGMENTS, _TSM_OUTPUTS).mean(dim=1)

    return RgbTsm()


def _load_parameters(path: Path, model: torch.nn.Module, torch_runtime: ModuleType) -> None:
    """Read the official Lightning container without allowing arbitrary pickle objects."""
    try:
        checkpoint = torch_runtime.load(path, map_location="cpu", weights_only=True)
    except UnpicklingError as exc:
        raise TsmModelError(f"The safe weights loader rejected the TSM checkpoint at {path}") from exc
    except (EOFError, OSError, RuntimeError, ValueError) as exc:
        raise TsmModelError(f"Could not read TSM weights at {path}: {exc}") from exc

    state = checkpoint.get("state_dict") if isinstance(checkpoint, Mapping) else None
    prefix = "model."
    if not isinstance(state, Mapping) or any(not isinstance(key, str) or not key.startswith(prefix)
                                             for key in state):
        raise TsmModelError("Expected the published EPIC RGB TSM checkpoint with model.* state_dict keys")

    parameters = {key.removeprefix(prefix): tensor for key, tensor in state.items()}
    expected = model.state_dict()
    missing = sorted(expected.keys() - parameters.keys())
    extra = sorted(parameters.keys() - expected.keys())
    if missing or extra:
        raise TsmModelError(f"Incompatible TSM parameters. Missing {missing[:4]}, unexpected {extra[:4]}")
    for key, reference in expected.items():
        parameter = parameters[key]
        if (not isinstance(parameter, torch_runtime.Tensor)
                or parameter.shape != reference.shape or parameter.dtype != reference.dtype):
            raise TsmModelError(f"Incompatible TSM tensor at {key}")
    model.load_state_dict(parameters, strict=True)


class TsmEncoder:
    """Score trimmed eight-frame RGB clips with an explicitly supplied TSM checkpoint."""

    def __init__(self, checkpoint: Path, *, device: str = "cpu") -> None:
        path = Path(checkpoint).expanduser()
        if not path.is_file():
            raise TsmModelError(f"TSM checkpoint file not found at {path}")
        try:
            import torch
            model = _build_network(torch)
        except (ImportError, OSError, RuntimeError) as exc:
            raise TsmModelError(f"Install compatible PyTorch and torchvision for optional TSM: {exc}") from exc

        self._torch = torch
        _load_parameters(path, model, torch)
        try:
            self._device = torch.device(device)
            self._model = model.to(self._device).eval()
        except (RuntimeError, ValueError) as exc:
            raise TsmModelError(f"Could not initialize TSM on {device!r}: {exc}") from exc

    def score_batch(
        self, clips: Sequence[Sequence[NDArray[np.uint8]]],
    ) -> tuple[NDArray[np.float32], NDArray[np.float32]]:
        """Return EPIC verb and noun logits in their published class-index order."""
        if len(clips) == 0:
            return (np.empty((0, TSM_VERB_COUNT), dtype=np.float32),
                    np.empty((0, TSM_NOUN_COUNT), dtype=np.float32))
        if any(len(clip) != TSM_SEGMENTS for clip in clips):
            raise ValueError(f"TSM requires exactly {TSM_SEGMENTS} RGB frames per clip")

        outputs = []
        with self._torch.inference_mode():
            for start in range(0, len(clips), _MAX_BATCH_CLIPS):
                batch = clips[start:start + _MAX_BATCH_CLIPS]
                pixels = np.stack([[_prepare_rgb_frame(frame) for frame in clip] for clip in batch])
                inputs = self._torch.from_numpy(pixels).to(self._device)
                logits = self._model(inputs).cpu().numpy()
                if logits.shape != (len(batch), _TSM_OUTPUTS) or not np.isfinite(logits).all():
                    raise TsmModelError("TSM returned invalid logits")
                outputs.append(logits)
        logits = np.concatenate(outputs, axis=0)
        return logits[:, :TSM_VERB_COUNT], logits[:, TSM_VERB_COUNT:]
