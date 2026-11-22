"""Visual changes, activity relevance, and action confidence for summarization."""
from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable, Sequence

from .models import ActionSegment, Highlight
from .normalize import as_real

if TYPE_CHECKING:
    import numpy as np


@dataclass(frozen=True)
class FrameEvidence:
    """Measured signals for one sampled frame, each on a [0, 1] scale."""

    timestamp: float
    motion: float
    novelty: float
    relevance: float
    transition: float = 0.0


@dataclass(frozen=True)
class ImportanceWeights:
    """Relative weights for the five frame importance signals."""

    motion: float = 0.30
    novelty: float = 0.25
    relevance: float = 0.20
    transition: float = 0.15
    action: float = 0.10


class VisualEvidence:
    """Extract change signals with a small amount of state per video."""

    THUMBNAIL_SIZE = 32
    HISTOGRAM_BINS = 4
    HISTORY_UPDATE = 0.20
    MOTION_FULL_SCALE = 0.25

    def __init__(self) -> None:
        self._previous: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None

    def update(self, rgb: np.ndarray) -> tuple[float, float, float]:
        """Return motion, recent-history novelty, and adjacent-frame transition."""
        import cv2
        import numpy as np

        if rgb.ndim != 3 or rgb.shape[2] != 3 or not rgb.size or rgb.dtype != np.uint8:
            raise ValueError("expected a nonempty RGB uint8 frame")
        size = self.THUMBNAIL_SIZE
        thumbnail = cv2.resize(rgb, (size, size), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(thumbnail, cv2.COLOR_RGB2GRAY).astype(np.float32)
        bins = self.HISTOGRAM_BINS
        channels = thumbnail // (256 // bins)
        indices = bins * (bins * channels[:, :, 0] + channels[:, :, 1]) + channels[:, :, 2]
        histogram = np.bincount(indices.ravel(), minlength=bins ** 3) / (size * size)

        motion = novelty = transition = 0.0
        history = histogram
        if self._previous is not None:
            previous_gray, previous_histogram, previous_history = self._previous
            # A mean quarter-range luminance change is strong motion at sampling resolution.
            delta = np.abs(gray - previous_gray).mean() / 255
            motion = min(1.0, float(delta / self.MOTION_FULL_SCALE))
            novelty = min(1.0, float(np.abs(histogram - previous_history).sum() / 2))
            transition = min(1.0, float(np.abs(histogram - previous_histogram).sum() / 2))
            history = (1 - self.HISTORY_UPDATE) * previous_history + self.HISTORY_UPDATE * histogram
        self._previous = gray, histogram, history
        return motion, novelty, transition


def score_action(action: ActionSegment) -> float:
    """Return normalized action confidence in [0, 1]."""
    start, end = as_real(action.start), as_real(action.end)
    if start is None or end is None or not (math.isfinite(start) and math.isfinite(end)):
        raise ValueError(f"Action interval must be finite numbers: {action!r}")
    if start < 0 or end <= start:
        raise ValueError(f"Invalid action interval: [{start}, {end}]")
    confidence = as_real(action.confidence)
    if confidence is None or not math.isfinite(confidence):
        raise ValueError(f"Action confidence must be a finite number, got {action.confidence!r}")
    return min(1.0, max(0.0, confidence))


def score_actions(actions: Iterable[ActionSegment]) -> list[Highlight]:
    """Turn actions into confidence-only candidates for the original selector."""
    return [Highlight(a.start, a.end, score_action(a)) for a in actions]


def score_frames(
    evidence: Sequence[FrameEvidence],
    actions: Iterable[ActionSegment],
    duration: float,
    weights: ImportanceWeights = ImportanceWeights(),
) -> list[float]:
    """Combine measured frame signals and maximum confidence of active actions."""
    raw_weights = (weights.motion, weights.novelty, weights.relevance, weights.transition, weights.action)
    ordered_weights = [as_real(weight) for weight in raw_weights]
    if any(weight is None or not math.isfinite(weight) or weight < 0 for weight in ordered_weights):
        raise ValueError("importance weights must be finite nonnegative numbers")
    # Scale before summing so valid large weights cannot overflow.
    max_weight = max(ordered_weights)
    if max_weight <= 0:
        raise ValueError("at least one importance weight must be positive")
    scaled_weights = [weight / max_weight for weight in ordered_weights]
    total_weight = sum(scaled_weights)
    if not evidence:
        raise ValueError("at least one sampled frame is required for highlight selection")

    timestamps: list[float] = []
    visual_scores: list[float] = []
    for frame in evidence:
        timestamp = as_real(frame.timestamp)
        if timestamp is None or not 0 <= timestamp < duration:
            raise ValueError("sample timestamps must be in [0, video duration)")
        if timestamps and timestamp <= timestamps[-1]:
            raise ValueError("sample timestamps must be strictly increasing")
        signals = (frame.motion, frame.novelty, frame.relevance, frame.transition)
        values = [as_real(signal) for signal in signals]
        if any(value is None or not 0 <= value <= 1 for value in values):
            raise ValueError("frame importance signals must be finite numbers in [0, 1]")
        timestamps.append(timestamp)
        visual_scores.append(sum(value * weight for value, weight in zip(values, scaled_weights)))

    confidence = [0.0] * len(evidence)
    for action in actions:
        strength = score_action(action)
        first = bisect_left(timestamps, action.start)
        last = bisect_left(timestamps, action.end, lo=first)
        for index in range(first, last):
            confidence[index] = max(confidence[index], strength)
    return [
        min(1.0, (visual_score + action_confidence * scaled_weights[-1]) / total_weight)
        for visual_score, action_confidence in zip(visual_scores, confidence)
    ]
