"""Budget-aware, non-overlapping, deterministic temporal highlight selection.

The video pipeline ranks short windows of sampled frame evidence. The original
candidate-based selector remains available to rank pre-existing intervals.
"""
from __future__ import annotations

import math
from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Sequence

from . import config
from .importance_scoring import FrameEvidence, ImportanceWeights, score_frames
from .models import ActionSegment, Highlight
from .normalize import as_real, floor_to_precision


class SkipReason(str, Enum):
    INVALID_CANDIDATE = "invalid_candidate"
    BELOW_MIN_DURATION = "below_min_duration"
    OVERLAPS_SELECTED = "overlaps_selected"
    EXCEEDS_REMAINING_BUDGET = "exceeds_remaining_budget"


@dataclass(frozen=True)
class SkippedCandidate:
    candidate: Highlight
    reason: SkipReason
    detail: str = ""


@dataclass(frozen=True)
class SelectionResult:
    highlights: list[Highlight]
    skipped: list[SkippedCandidate] = field(default_factory=list)
    budget_s: float = 0.0
    used_s: float = 0.0


def _finite(value: object) -> float | None:
    number = as_real(value)
    return number if number is not None and math.isfinite(number) else None


def _overlaps(a: Highlight, others: Iterable[Highlight]) -> bool:
    return any(not (a.end <= b.start or a.start >= b.end) for b in others)


def _trim_window(c: Highlight, remaining: float, min_len: float) -> Highlight | None:
    """Centered window of at most `remaining` seconds, or None if too short."""
    precision = config.TIME_PRECISION_DECIMALS
    length = floor_to_precision(remaining, precision)
    if length <= 0 or length < min_len or length >= (c.end - c.start):
        return None
    mid = (c.start + c.end) / 2.0
    start = max(c.start, round(mid - length / 2.0, precision))
    end = min(c.end, round(start + length, precision))
    return Highlight(start, end, c.importance) if end > start else None


def _selection_settings(
    video_duration: float, budget_ratio: float, min_segment_s: float,
) -> tuple[float, float, float]:
    duration = _finite(video_duration)
    if duration is None or duration <= 0:
        raise ValueError("video_duration must be a finite positive number")
    ratio = _finite(budget_ratio)
    if ratio is None or not 0 < ratio <= 1:
        raise ValueError("budget_ratio must be a finite number in (0, 1]")
    min_len = _finite(min_segment_s)
    if min_len is None or min_len < 0:
        raise ValueError("min_segment_s must be a finite number >= 0")
    return duration, ratio, min_len


def select_highlights_with_report(
    candidates: Iterable[Highlight],
    video_duration: float,
    budget_ratio: float = config.HIGHLIGHT_BUDGET_RATIO,
    min_segment_s: float = config.MIN_HIGHLIGHT_SEGMENT_S,
    trim_to_fit: bool = config.TRIM_TO_FIT,
) -> SelectionResult:
    duration, ratio, min_len = _selection_settings(video_duration, budget_ratio, min_segment_s)
    budget = duration * ratio
    skipped: list[SkippedCandidate] = []
    valid: list[Highlight] = []

    for cand in candidates:
        start = _finite(getattr(cand, "start", None))
        end = _finite(getattr(cand, "end", None))
        score = _finite(getattr(cand, "importance", None))
        if start is None or end is None or score is None:
            skipped.append(SkippedCandidate(cand, SkipReason.INVALID_CANDIDATE,
                                            "non-finite or non-numeric field"))
            continue
        if start < 0 or end <= start or end > duration + config.TIME_EPSILON:
            skipped.append(SkippedCandidate(cand, SkipReason.INVALID_CANDIDATE,
                                            f"interval [{start}, {end}] outside [0, {duration}]"))
            continue
        if end - start < min_len:
            skipped.append(SkippedCandidate(cand, SkipReason.BELOW_MIN_DURATION,
                                            f"{end - start:.3f}s < {min_len}s"))
            continue
        valid.append(Highlight(start, end, min(1.0, max(0.0, score))))

    # Total order => result does not depend on the order candidates were supplied.
    valid.sort(key=lambda c: (-(c.importance / (c.end - c.start)), -c.importance, c.start, c.end))

    selected: list[Highlight] = []
    used = 0.0
    for cand in valid:
        remaining = budget - used
        window: Highlight | None = cand
        if cand.end - cand.start > remaining + config.BUDGET_EPSILON:
            window = _trim_window(cand, remaining, min_len) if trim_to_fit else None
            if window is None:
                skipped.append(SkippedCandidate(
                    cand, SkipReason.EXCEEDS_REMAINING_BUDGET,
                    f"{cand.end - cand.start:.3f}s > remaining {max(remaining, 0.0):.3f}s"))
                continue
        if _overlaps(window, selected):
            skipped.append(SkippedCandidate(cand, SkipReason.OVERLAPS_SELECTED))
            continue
        selected.append(window)
        used += window.end - window.start

    selected.sort(key=lambda h: (h.start, h.end))
    return SelectionResult(selected, skipped, budget, used)


def select_highlights(
    candidates: Iterable[Highlight],
    video_duration: float,
    budget_ratio: float = config.HIGHLIGHT_BUDGET_RATIO,
    min_segment_s: float = config.MIN_HIGHLIGHT_SEGMENT_S,
    trim_to_fit: bool = config.TRIM_TO_FIT,
) -> list[Highlight]:
    """Convenience wrapper returning only the selected highlights."""
    return select_highlights_with_report(
        candidates, video_duration, budget_ratio, min_segment_s, trim_to_fit
    ).highlights


def _rank_windows(
    evidence: Sequence[FrameEvidence], scores: Sequence[float],
    width: int, duration_ticks: int, scale: int,
) -> list[tuple[int, float]]:
    """Score windows with a prefix integral of the sampled importance curve."""
    boundaries = [0.0, *(frame.timestamp for frame in evidence[1:])]
    area = [0.0]
    for index, (left, right) in enumerate(zip(boundaries, boundaries[1:])):
        area.append(area[-1] + (right - left) * scores[index])

    def integral(tick: int) -> float:
        seconds = tick / scale
        index = bisect_right(boundaries, seconds) - 1
        return area[index] + (seconds - boundaries[index]) * scores[index]

    tail = duration_ticks - width
    # Include a disjoint tiling, the last possible window, and both alignments
    # of a window edge with frame evidence changes.
    starts = set(range(0, tail + 1, width))
    starts.add(tail)
    for boundary in boundaries:
        tick = round(boundary * scale)
        starts.add(min(tail, tick))
        starts.add(max(0, min(tail, tick - width)))
    seconds_per_window = width / scale
    windows = [
        (start, min(1.0, max(0.0, (integral(start + width) - integral(start)) / seconds_per_window)))
        for start in starts
    ]
    # Ignore floating-point noise when otherwise equal windows tie.
    return sorted(windows, key=lambda window: (-round(window[1], 12), window[0]))


def _floor_ticks(seconds: float, scale: int) -> int:
    """Find the last output timestamp at or before the original seconds."""
    nearest = round(seconds * scale)
    return nearest - int(nearest / scale > seconds)


def _fit_index(start: int, width: int, picked: Sequence[int]) -> int | None:
    """Return the insertion point when a window misses both neighbors."""
    index = bisect_left(picked, start)
    if index and picked[index - 1] + width > start:
        return None
    if index < len(picked) and picked[index] < start + width:
        return None
    return index


def select_video_highlights(
    evidence: Sequence[FrameEvidence],
    actions: Iterable[ActionSegment],
    duration: float,
    *,
    profile: str,
    budget_ratio: float = config.HIGHLIGHT_BUDGET_RATIO,
    min_segment_s: float = config.MIN_HIGHLIGHT_SEGMENT_S,
    target_segment_s: float = 6.0,
    importance_weights: ImportanceWeights = ImportanceWeights(),
    short_policy: str = "minimum",
) -> SelectionResult:
    """Rank evidence windows on the serialization grid and join adjacent picks.

    The recommended budget is always reported as `duration * budget_ratio`.
    With readme6, the minimum policy uses four seconds if the budget is smaller
    and the source has four seconds. Videos shorter than four seconds retain
    their target budget with a one-tick minimum when a tick fits the source.
    """
    duration, ratio, min_len = _selection_settings(duration, budget_ratio, min_segment_s)
    if short_policy not in {"minimum", "budget"}:
        raise ValueError("short_policy must be 'minimum' or 'budget'")
    if profile not in {"readme6", "slide4"}:
        raise ValueError(f"unknown highlight profile {profile!r}")
    target = _finite(target_segment_s)
    if target is None or target <= 0:
        raise ValueError("target_segment_s must be a finite positive number")

    decimals = config.README6_TIME_DECIMALS if profile == "readme6" else config.SLIDE4_TIME_DECIMALS
    scale = 10 ** decimals
    duration_ticks = _floor_ticks(duration, scale)
    budget_s = duration * ratio
    budget_ticks = min(duration_ticks, _floor_ticks(budget_s, scale))
    readme_min = math.ceil(config.README6_MIN_HIGHLIGHT_SEGMENT_S * scale)
    if profile == "readme6" and short_policy == "minimum" and duration_ticks:
        budget_ticks = max(budget_ticks, readme_min if duration_ticks >= readme_min else 1)
    scores = score_frames(evidence, actions, duration, importance_weights)
    if not budget_ticks:
        return SelectionResult([], budget_s=budget_s)

    minimum_ticks = max(1, math.ceil(min_len * scale - config.BUDGET_EPSILON))
    if profile == "readme6":
        minimum_ticks = max(minimum_ticks, readme_min)
    minimum_ticks = min(minimum_ticks, budget_ticks)
    target_ticks = max(minimum_ticks, round(target * scale))
    count = max(1, min(budget_ticks // minimum_ticks, round(budget_ticks / target_ticks)))
    width = budget_ticks // count
    ranked = _rank_windows(evidence, scores, width, duration_ticks, scale)

    chosen: dict[int, float] = {}
    ordered_starts: list[int] = []
    for start, importance in ranked:
        insertion = _fit_index(start, width, ordered_starts)
        if insertion is not None:
            chosen[start] = importance
            ordered_starts.insert(insertion, start)
            if len(chosen) == count:
                break
    if len(chosen) < count:
        # With a high custom budget, greedy placements can block otherwise
        # affordable windows. The top windows from the disjoint tiling fit.
        tiled = [(start, score) for start, score in ranked if start % width == 0]
        chosen = dict(tiled[:count])
        ordered_starts = sorted(chosen)

    runs: list[tuple[int, int, float]] = []
    for start in ordered_starts:
        score = chosen[start]
        end = start + width
        if runs and runs[-1][1] == start:
            start, _, previous_score = runs.pop()
            score += previous_score
        runs.append((start, end, score))
    highlights = [
        Highlight(start / scale, end / scale, score / ((end - start) // width))
        for start, end, score in runs
    ]

    skipped = []
    for start, importance in ranked:
        if start in chosen:
            continue
        overlap = _fit_index(start, width, ordered_starts) is None
        reason = SkipReason.OVERLAPS_SELECTED if overlap else SkipReason.EXCEEDS_REMAINING_BUDGET
        skipped.append(SkippedCandidate(Highlight(start / scale, (start + width) / scale, importance), reason))
    return SelectionResult(highlights, skipped, budget_s, len(chosen) * width / scale)
