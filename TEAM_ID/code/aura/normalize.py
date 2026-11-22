"""Numerical and temporal validation of raw action predictions.

Runs once, directly after recognition, so every later stage can assume finite,
in-range, millisecond-rounded, deterministically ordered actions. Nothing is
dropped silently: every rejection is recorded in a `NormalizationReport`.
Labels are never altered or invented; long actions are never rejected for length.
"""
from __future__ import annotations

import math
import numbers
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

from . import config
from .models import ActionSegment, RawAction


class NormalizationError(ValueError):
    """Raised for unusable normalization parameters (not for bad predictions)."""


class RejectReason(str, Enum):
    MALFORMED = "malformed"
    INVALID_LABEL = "invalid_label"
    NON_NUMERIC_TIME = "non_numeric_time"
    NON_FINITE_TIME = "non_finite_time"
    NON_POSITIVE_DURATION = "non_positive_duration"
    OUT_OF_RANGE = "out_of_range"
    EMPTY_AFTER_CLIPPING = "empty_after_clipping"
    INVALID_CONFIDENCE = "invalid_confidence"


@dataclass(frozen=True)
class RejectedAction:
    index: int
    reason: RejectReason
    detail: str = ""


@dataclass
class NormalizationReport:
    total_in: int = 0
    kept: int = 0
    clipped: int = 0
    confidence_clamped: int = 0
    rejected: list[RejectedAction] = field(default_factory=list)

    def reason_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.rejected:
            counts[item.reason.value] = counts.get(item.reason.value, 0) + 1
        return counts

    def summary(self) -> str:
        parts = [
            f"in={self.total_in}",
            f"kept={self.kept}",
            f"rejected={len(self.rejected)}",
            f"clipped={self.clipped}",
            f"confidence_clamped={self.confidence_clamped}",
        ]
        if self.rejected:
            parts.append(f"reasons={self.reason_counts()}")
        return " ".join(parts)


def as_real(value: Any) -> float | None:
    """Return `value` as a float if it is a real number (not bool), else None.

    Strings, None and bools are deliberately rejected rather than coerced.
    """
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return None
    try:
        return float(value)
    except OverflowError:
        return math.inf
    except (TypeError, ValueError):
        return None


def validate_duration(duration: Any) -> float:
    value = as_real(duration)
    if value is None or not math.isfinite(value) or value <= 0:
        raise NormalizationError(
            f"duration must be a finite positive number of seconds, got {duration!r}"
        )
    return value


def floor_to_precision(value: float, precision: int) -> float:
    scale = 10 ** precision
    return math.floor(value * scale + 1e-9) / scale


def normalize_actions(
    actions: Iterable[RawAction],
    duration: float,
    *,
    tolerance_s: float = config.BOUNDARY_TOLERANCE_S,
    precision: int = config.TIME_PRECISION_DECIMALS,
) -> tuple[list[ActionSegment], NormalizationReport]:
    """Validate, clip, round and order predictions.

    Returns (normalized actions, report). Output is sorted by a total order
    (start, end, verb, noun, -confidence), so it does not depend on the order
    in which the recognizer emitted predictions.
    """
    duration = validate_duration(duration)
    tolerance = as_real(tolerance_s)
    if tolerance is None or not math.isfinite(tolerance) or tolerance < 0:
        raise NormalizationError(f"tolerance_s must be finite and >= 0, got {tolerance_s!r}")
    limit = floor_to_precision(duration, precision)
    if limit <= 0:
        raise NormalizationError(f"duration {duration} is shorter than the time precision")

    report = NormalizationReport()
    kept: list[ActionSegment] = []

    def reject(index: int, reason: RejectReason, detail: str = "") -> None:
        report.rejected.append(RejectedAction(index, reason, detail))

    for index, raw in enumerate(actions):
        report.total_in += 1

        if isinstance(raw, ActionSegment):
            action = raw
        else:
            try:
                action = ActionSegment.from_mapping(raw)  # type: ignore[arg-type]
            except ValueError as exc:
                reject(index, RejectReason.MALFORMED, str(exc))
                continue

        bad_label = next(
            (name for name in ("verb", "noun")
             if not isinstance(getattr(action, name), str) or not getattr(action, name).strip()),
            None,
        )
        if bad_label is not None:
            reject(index, RejectReason.INVALID_LABEL, f"{bad_label}={getattr(action, bad_label)!r}")
            continue

        start, end = as_real(action.start), as_real(action.end)
        if start is None or end is None:
            reject(index, RejectReason.NON_NUMERIC_TIME,
                   f"start={action.start!r} end={action.end!r}")
            continue
        if not (math.isfinite(start) and math.isfinite(end)):
            reject(index, RejectReason.NON_FINITE_TIME, f"start={start} end={end}")
            continue
        if end <= start:
            reject(index, RejectReason.NON_POSITIVE_DURATION, f"start={start} end={end}")
            continue
        if start < -tolerance or end > duration + tolerance or start >= duration:
            reject(index, RejectReason.OUT_OF_RANGE,
                   f"start={start} end={end} duration={duration}")
            continue

        confidence = as_real(action.confidence)
        if confidence is None or not math.isfinite(confidence):
            reject(index, RejectReason.INVALID_CONFIDENCE, f"confidence={action.confidence!r}")
            continue

        was_clipped = start < 0.0 or end > duration + config.TIME_EPSILON
        new_start = round(max(start, 0.0), precision)
        new_end = min(round(min(end, limit), precision), limit)
        if new_end <= new_start:
            reject(index, RejectReason.EMPTY_AFTER_CLIPPING,
                   f"start={start} end={end} -> [{new_start}, {new_end}]")
            continue

        clamped = min(1.0, max(0.0, confidence))
        if clamped != confidence:
            report.confidence_clamped += 1
        if was_clipped:
            report.clipped += 1
        kept.append(ActionSegment(action.verb, action.noun, new_start, new_end, clamped))

    kept.sort(key=lambda a: (a.start, a.end, a.verb, a.noun, -a.confidence))
    report.kept = len(kept)
    return kept, report
