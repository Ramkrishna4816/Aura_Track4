"""Experimental fixed-budget highlight planners driven by model evidence."""
from __future__ import annotations

import math
from bisect import insort
from collections.abc import Iterable, Mapping, Sequence

from . import config
from .highlight_selection import (
    SelectionResult,
    SkippedCandidate,
    SkipReason,
    _finite,
    _fit_index,
    _floor_ticks,
    _rank_windows,
    _selection_settings,
)
from .importance_scoring import FrameEvidence, ImportanceWeights, score_action, score_frames
from .models import ActionSegment, Highlight

STRATEGIES = ("distinct", "balanced", "exchange")

# This fraction governs how a window can represent a predicted action during
# inference. It does not represent an organizer capture rule.
_PREDICTED_CAPTURE_FRACTION = 0.5
Pair = tuple[str, str]
PairEvidence = dict[Pair, float]


def _grid(
    duration: float, profile: str, ratio: float, minimum: float, target: float, short_policy: str,
) -> tuple[int, int, int, int]:
    """Use the released centisecond and short-video policy for every strategy."""
    decimals = config.README6_TIME_DECIMALS if profile == "readme6" else config.SLIDE4_TIME_DECIMALS
    scale = 10 ** decimals
    duration_ticks = _floor_ticks(duration, scale)
    budget_ticks = min(duration_ticks, _floor_ticks(duration * ratio, scale))
    readme_minimum = math.ceil(config.README6_MIN_HIGHLIGHT_SEGMENT_S * scale)
    if profile == "readme6" and short_policy == "minimum" and duration_ticks:
        budget_ticks = max(budget_ticks, readme_minimum if duration_ticks >= readme_minimum else 1)
    if not budget_ticks:
        return scale, duration_ticks, 0, 0

    minimum_ticks = max(1, math.ceil(minimum * scale - config.BUDGET_EPSILON))
    if profile == "readme6":
        minimum_ticks = max(minimum_ticks, readme_minimum)
    minimum_ticks = min(minimum_ticks, budget_ticks)
    target_ticks = max(minimum_ticks, round(target * scale))
    count = max(1, min(budget_ticks // minimum_ticks, round(budget_ticks / target_ticks)))
    return scale, duration_ticks, count, budget_ticks // count


def _window_pairs(
    starts: Iterable[int], width: int, scale: int, actions: Sequence[ActionSegment],
) -> dict[int, PairEvidence]:
    """Keep the strongest qualifying predicted instance of each pair per window."""
    scored = sorted(
        (a.start, a.end, (a.verb, a.noun), score_action(a)) for a in actions
        if a.verb != "other" and a.noun != "other" and a.confidence > 0
    )
    active: list[tuple[float, float, Pair, float]] = []
    next_action = 0
    result = {}
    for start in sorted(starts):
        left, right = start / scale, (start + width) / scale
        while next_action < len(scored) and scored[next_action][0] < right:
            active.append(scored[next_action])
            next_action += 1
        active = [item for item in active if item[1] > left]
        pairs: PairEvidence = {}
        for onset, offset, pair, confidence in active:
            overlap = min(right, offset) - max(left, onset)
            if overlap + config.TIME_EPSILON >= (offset - onset) * _PREDICTED_CAPTURE_FRACTION:
                pairs[pair] = max(pairs.get(pair, 0.0), confidence)
        result[start] = pairs
    return result


def _add_evidence(current: PairEvidence, candidate: Mapping[Pair, float]) -> None:
    for pair, strength in candidate.items():
        current[pair] = max(current.get(pair, 0.0), strength)


def _gain(current: Mapping[Pair, float], candidate: Mapping[Pair, float]) -> float:
    return math.fsum(max(0.0, strength - current.get(pair, 0.0)) for pair, strength in candidate.items())


def _pair_greedy(
    quality: Mapping[int, float], evidence: Mapping[int, PairEvidence], width: int, count: int,
) -> list[int]:
    """Choose windows by marginal confidence-weighted coverage of distinct pairs."""
    picked: list[int] = []
    covered: PairEvidence = {}
    for _ in range(count):
        candidates = (start for start in quality if _fit_index(start, width, picked) is not None)
        start = max(
            candidates, key=lambda s: (round(_gain(covered, evidence[s]), 12), round(quality[s], 12), -s),
            default=None,
        )
        if start is None:
            break
        _add_evidence(covered, evidence[start])
        insort(picked, start)
    return picked


def _quality_greedy(quality: Mapping[int, float], width: int, count: int) -> list[int]:
    picked: list[int] = []
    for start in quality:  # The common candidate generator supplies quality-ranked order.
        position = _fit_index(start, width, picked)
        if position is not None:
            picked.insert(position, start)
            if len(picked) == count:
                break
    return picked


def _stratified_quality(quality: Mapping[int, float], width: int, count: int, duration: int) -> list[int]:
    """Pick the strongest measured window in each chronological stratum."""
    picked = {}
    for start in quality:
        # Find the interval's stratum using the same integer boundaries below.
        group = ((start + 1) * count - 1) // duration
        if group not in picked and start + width <= ((group + 1) * duration) // count:
            picked[group] = start
            if len(picked) == count:
                break
    return sorted(picked.values())


def _quality_seed(quality: Mapping[int, float], width: int, count: int) -> list[int]:
    picked = _quality_greedy(quality, width, count)
    if len(picked) == count:
        return picked
    # The candidate grid always contains the complete disjoint tiling.
    return sorted([start for start in quality if start % width == 0][:count])


def _exchange(
    quality: Mapping[int, float], evidence: Mapping[int, PairEvidence], width: int, count: int,
) -> list[int]:
    """Improve an importance-ranked seed with one sweep of feasible swaps."""
    picked = _quality_seed(quality, width, count)
    possible: PairEvidence = {}
    for pairs in evidence.values():
        _add_evidence(possible, pairs)
    total_pair_strength = math.fsum(possible.values())
    if not total_pair_strength:
        return picked

    # Normalize both terms to [0, 1] for the whole selection. A replacement can
    # trade mean measured importance for greater saturated pair coverage.
    for original in tuple(picked):
        kept = [start for start in picked if start != original]
        covered: PairEvidence = {}
        for start in kept:
            _add_evidence(covered, evidence[start])

        def value(start: int) -> float:
            return quality[start] / count + _gain(covered, evidence[start]) / total_pair_strength

        replacement = max(
            (start for start in quality if _fit_index(start, width, kept) is not None),
            key=lambda start: (round(value(start), 12), round(quality[start], 12), -start),
        )
        if value(replacement) > value(original) + 1e-12:
            picked = sorted([*kept, replacement])
    return picked


def _report(
    chosen: Sequence[int], quality: Mapping[int, float], width: int, scale: int, budget: float,
) -> SelectionResult:
    runs: list[tuple[int, int, float]] = []
    for start in chosen:
        end = start + width
        score = quality[start]
        if runs and runs[-1][1] == start:
            start, _, previous_score = runs.pop()
            score += previous_score
        runs.append((start, end, score))
    highlights = [
        Highlight(start / scale, end / scale, score / ((end - start) // width))
        for start, end, score in runs
    ]
    selected = set(chosen)
    skipped = [
        SkippedCandidate(
            Highlight(start / scale, (start + width) / scale, importance),
            SkipReason.OVERLAPS_SELECTED if _fit_index(start, width, chosen) is None
            else SkipReason.EXCEEDS_REMAINING_BUDGET,
        )
        for start, importance in quality.items() if start not in selected
    ]
    return SelectionResult(highlights, skipped, budget, len(chosen) * width / scale)


def select_competition_highlights(
    evidence: Sequence[FrameEvidence],
    actions: Iterable[ActionSegment],
    duration: float,
    *,
    profile: str,
    strategy: str = "distinct",
    budget_ratio: float = config.HIGHLIGHT_BUDGET_RATIO,
    min_segment_s: float = config.MIN_HIGHLIGHT_SEGMENT_S,
    target_segment_s: float = 6.0,
    importance_weights: ImportanceWeights = ImportanceWeights(),
    short_policy: str = "minimum",
) -> SelectionResult:
    """Compare three deterministic planners under the released highlight geometry.

    Distinct uses novel predicted pairs to rank each pick. Balanced spreads
    quality picks across chronological strata. Exchange starts from a quality
    plan and tests a single replacement per pick. Only model evidence enters.
    """
    duration, ratio, minimum = _selection_settings(duration, budget_ratio, min_segment_s)
    if short_policy not in {"minimum", "budget"}:
        raise ValueError("short_policy must be 'minimum' or 'budget'")
    if profile not in {"readme6", "slide4"}:
        raise ValueError(f"unknown highlight profile {profile!r}")
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown highlight strategy {strategy!r}")
    target = _finite(target_segment_s)
    if target is None or target <= 0:
        raise ValueError("target_segment_s must be a finite positive number")

    actions = tuple(actions)
    scores = score_frames(evidence, actions, duration, importance_weights)
    scale, duration_ticks, count, width = _grid(duration, profile, ratio, minimum, target, short_policy)
    budget = duration * ratio
    if not width:
        return SelectionResult([], budget_s=budget)
    quality = dict(_rank_windows(evidence, scores, width, duration_ticks, scale))
    if strategy == "balanced":
        chosen = _stratified_quality(quality, width, count, duration_ticks)
        if len(chosen) != count:
            chosen = _quality_seed(quality, width, count)
    else:
        pairs = _window_pairs(quality, width, scale, actions)
        if strategy == "exchange":
            chosen = _exchange(quality, pairs, width, count)
        else:
            chosen = _pair_greedy(quality, pairs, width, count)
            if len(chosen) != count:
                tiled = {start: score for start, score in quality.items() if start % width == 0}
                chosen = _pair_greedy(tiled, pairs, width, count)
    return _report(chosen, quality, width, scale, budget)
