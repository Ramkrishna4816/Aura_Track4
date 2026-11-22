"""CPU inference for the pinned CLIP ViT-B/32 ONNX export."""
from __future__ import annotations

import hashlib
from collections.abc import Sequence
from pathlib import Path

import numpy as np


MODEL_REPOSITORY = "Xenova/clip-vit-base-patch32"
MODEL_REVISION = "6b7c523703ae26e39be4b03774966f8571c7f523"
VISION_WEIGHTS = "vision_model_uint8.onnx"
TEXT_WEIGHTS = "text_model_uint8.onnx"
TOKENIZER_FILE = "tokenizer.json"
# Local filename -> (path within the pinned repository, SHA-256).
WEIGHT_ASSETS = {
    VISION_WEIGHTS: (
        f"onnx/{VISION_WEIGHTS}",
        "b95448754a6ae56964ec80c570c80bb9863787ee85f51b664abed8c0e5f22a7a",
    ),
    TEXT_WEIGHTS: (
        f"onnx/{TEXT_WEIGHTS}",
        "cbe64fd9eaa6324d49006ce99c104107fdf6b26d25bebff96ecbb5d8a24c5e54",
    ),
    TOKENIZER_FILE: (
        TOKENIZER_FILE,
        "f7f3b7af117d467b58374797691a6438d3e6b9e9cef800dfd5dced7f697a90cd",
    ),
}
DEFAULT_WEIGHTS_DIR = Path(__file__).resolve().parents[2] / "weights"

_IMAGE_SIZE = 224
_IMAGE_MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
_IMAGE_STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)
_EMBEDDING_SIZE = 512
_CONTEXT_LENGTH = 77
_END_OF_TEXT = "<|endoftext|>"
_END_OF_TEXT_ID = 49407
_IMAGE_BATCH_SIZE = 8
_TEXT_BATCH_SIZE = 64


class ClipModelError(RuntimeError):
    """Raised when the model files or inference runtime cannot be used."""


def has_expected_sha256(path: Path, expected: str) -> bool:
    """Check a weight file without loading it into memory."""
    if not path.is_file():
        return False
    digest = hashlib.sha256()
    with path.open("rb") as contents:
        for block in iter(lambda: contents.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest() == expected


def _prepare_image(frame: np.ndarray) -> np.ndarray:
    from PIL import Image

    if frame.ndim != 3 or frame.shape[2] != 3 or frame.dtype != np.uint8:
        raise ValueError("CLIP frames must be RGB uint8 arrays with shape (height, width, 3)")
    height, width = frame.shape[:2]
    short_side = min(height, width)
    if short_side == 0:
        raise ValueError("CLIP frames must have positive height and width")
    resized_width = width * _IMAGE_SIZE // short_side
    resized_height = height * _IMAGE_SIZE // short_side
    image = Image.fromarray(frame).resize((resized_width, resized_height), Image.Resampling.BICUBIC)
    left = (resized_width - _IMAGE_SIZE) // 2
    top = (resized_height - _IMAGE_SIZE) // 2
    crop = image.crop((left, top, left + _IMAGE_SIZE, top + _IMAGE_SIZE))
    pixels = np.asarray(crop, dtype=np.float32) / np.float32(255)
    return ((pixels - _IMAGE_MEAN) / _IMAGE_STD).transpose(2, 0, 1)


def _normalize(embeddings: np.ndarray, count: int) -> np.ndarray:
    if embeddings.shape != (count, _EMBEDDING_SIZE) or not np.isfinite(embeddings).all():
        raise ClipModelError("CLIP returned invalid embeddings")
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    if not np.isfinite(norms).all() or (norms <= 0).any():
        raise ClipModelError("CLIP returned an embedding with an invalid norm")
    return embeddings / norms


class ClipEncoder:
    """Encode RGB frames and text prompts as unit vectors in CLIP's joint space."""

    # Verified from the combined ONNX export at the same revision. The split
    # exports return projected embeddings without applying this multiplier.
    logit_scale = 100.0

    def __init__(self, weights_dir: Path = DEFAULT_WEIGHTS_DIR) -> None:
        weights_dir = Path(weights_dir).expanduser()
        invalid_assets = [
            filename for filename, (_, digest) in WEIGHT_ASSETS.items()
            if not has_expected_sha256(weights_dir / filename, digest)
        ]
        if invalid_assets:
            raise ClipModelError(
                f"Missing or corrupt CLIP files in {weights_dir}: {', '.join(invalid_assets)}. "
                f"Run python code/fetch_weights.py --weights-dir \"{weights_dir.resolve()}\" "
                "from the submission directory."
            )

        try:
            import onnxruntime as ort
            from tokenizers import Tokenizer
        except ImportError as exc:
            raise ClipModelError("Install the CLIP runtime with pip install -r requirements.txt") from exc

        options = ort.SessionOptions()
        # Small bounded batches also work on shared or low-memory CPU hosts.
        options.intra_op_num_threads = 2
        options.inter_op_num_threads = 1
        try:
            self._vision = ort.InferenceSession(
                str(weights_dir / VISION_WEIGHTS), sess_options=options, providers=["CPUExecutionProvider"]
            )
            self._text = ort.InferenceSession(
                str(weights_dir / TEXT_WEIGHTS), sess_options=options, providers=["CPUExecutionProvider"]
            )
            self._tokenizer = Tokenizer.from_file(str(weights_dir / TOKENIZER_FILE))
            self._tokenizer.enable_truncation(max_length=_CONTEXT_LENGTH)
            self._tokenizer.enable_padding(pad_id=_END_OF_TEXT_ID, pad_token=_END_OF_TEXT)
        except Exception as exc:
            raise ClipModelError(f"Could not initialize the local CLIP models: {exc}") from exc

    def encode_images(self, frames: Sequence[np.ndarray]) -> np.ndarray:
        """Run CLIP vision inference in bounded batches and preserve frame order."""
        if len(frames) == 0:
            return np.empty((0, _EMBEDDING_SIZE), dtype=np.float32)
        batches = []
        for start in range(0, len(frames), _IMAGE_BATCH_SIZE):
            pixels = np.stack([_prepare_image(frame) for frame in frames[start:start + _IMAGE_BATCH_SIZE]])
            embeddings, = self._vision.run(["image_embeds"], {"pixel_values": np.ascontiguousarray(pixels)})
            batches.append(_normalize(embeddings, len(pixels)))
        return np.concatenate(batches, axis=0)

    def encode_text(self, prompts: Sequence[str]) -> np.ndarray:
        """Run CLIP text inference in bounded batches and preserve prompt order."""
        if len(prompts) == 0:
            return np.empty((0, _EMBEDDING_SIZE), dtype=np.float32)
        batches = []
        for start in range(0, len(prompts), _TEXT_BATCH_SIZE):
            encoded = self._tokenizer.encode_batch(list(prompts[start:start + _TEXT_BATCH_SIZE]))
            # The split export's sole input is input_ids. Right-side EOS padding
            # cannot change the causal features at the first EOS position.
            input_ids = np.array([entry.ids for entry in encoded], dtype=np.int64)
            embeddings, = self._text.run(["text_embeds"], {"input_ids": input_ids})
            batches.append(_normalize(embeddings, len(encoded)))
        return np.concatenate(batches, axis=0)
