"""Video metadata and timestamp sampling utilities."""
from __future__ import annotations

import math
import os
from collections.abc import Iterator
from typing import TYPE_CHECKING, TypedDict

from . import config

if TYPE_CHECKING:
    from numpy import ndarray


class VideoDecodeError(ValueError):
    """The video cannot supply the frames described by its metadata."""


class VideoInfo(TypedDict):
    fps: float
    frame_count: int
    width: int
    height: int
    duration: float


def get_video_info(video_path: str | os.PathLike[str]) -> VideoInfo:
    """Return fps, frame_count, width, height and duration (seconds).

    Raises ValueError for missing/unreadable files or non-finite/non-positive
    fps or frame count. `cv2` is imported lazily so the rest of the package (and
    its tests) do not require OpenCV.
    """
    path = os.fspath(video_path)
    if not os.path.isfile(path):
        raise ValueError(f"Video file not found: {path}")
    import cv2

    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {path}")
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
        count = float(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0.0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    finally:
        cap.release()
    if not math.isfinite(fps) or fps <= 0 or not math.isfinite(count) or count < 1:
        raise ValueError(f"Video has invalid FPS ({fps}) or frame count ({count}).")
    frame_count = int(count)
    duration = frame_count / fps
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(f"Video has invalid duration ({duration}).")
    return {
        "fps": fps,
        "frame_count": frame_count,
        "width": width,
        "height": height,
        "duration": duration,
    }


def sample_timestamps(duration: float, sample_fps: float = config.SAMPLE_FPS) -> list[float]:
    """Return deterministic sample times in [0, duration), excluding the endpoint.

    The count is ceil(duration * sample_fps) so the last in-range sample is kept
    (the previous floor() dropped it). At least one sample (t=0) is returned.
    """
    if not (math.isfinite(duration) and math.isfinite(sample_fps)):
        raise ValueError("duration and sample_fps must be finite")
    if duration <= 0 or sample_fps <= 0:
        raise ValueError("duration and sample_fps must be positive")
    count = max(1, math.ceil(duration * sample_fps - 1e-9))
    return [i / sample_fps for i in range(count)]


def sample_video(
    video_path: str | os.PathLike[str],
    info: VideoInfo,
    sample_fps: float = config.SAMPLE_FPS,
) -> Iterator[tuple[float, ndarray]]:
    """Decode once in frame order and yield clocked RGB thumbnails.

    The constant-frame-rate clock uses source frame indices divided by metadata
    FPS. Grab unsampled frames without an RGB conversion and retain one image
    at a time. Variable-frame-rate inputs are approximated by this clock.
    """
    import cv2

    fps, frame_count = info["fps"], info["frame_count"]
    timestamps = sample_timestamps(info["duration"], min(sample_fps, fps))
    cap = cv2.VideoCapture(os.fspath(video_path))
    index = -1
    try:
        if not cap.isOpened():
            raise VideoDecodeError(f"Cannot reopen video: {video_path}")
        for timestamp in timestamps:
            target = min(frame_count - 1, round(timestamp * fps))
            if target <= index:
                continue
            while index < target:
                if not cap.grab():
                    raise VideoDecodeError(f"Video ended before sampled frame {target}: {video_path}")
                index += 1
            ok, frame = cap.retrieve()
            if not ok or frame is None or frame.size == 0:
                raise VideoDecodeError(f"Cannot decode frame {index}: {video_path}")
            height, width = frame.shape[:2]
            if max(height, width) > config.SAMPLE_MAX_SIDE_PX:
                scale = config.SAMPLE_MAX_SIDE_PX / max(height, width)
                frame = cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))),
                                   interpolation=cv2.INTER_AREA)
            yield index / fps, cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    except cv2.error as exc:
        raise VideoDecodeError(f"OpenCV failed while decoding {video_path}: {exc}") from exc
    finally:
        cap.release()
