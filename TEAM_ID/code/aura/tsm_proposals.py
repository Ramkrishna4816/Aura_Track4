"""Experimental temporal proposals for the EPIC-KITCHENS RGB TSM."""
from __future__ import annotations

import csv
import math
import os
import time
from collections import Counter, defaultdict
from collections.abc import Iterator, Sequence
from contextlib import closing
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from typing import Protocol

import numpy as np

from .models import ActionSegment
from .preprocessing import VideoDecodeError, VideoInfo
from .taxonomy import Taxonomy
from .tsm_backend import TSM_NOUN_COUNT, TSM_SEGMENTS, TSM_VERB_COUNT

PAIR_PRIOR_POWER = 0.125
PAIR_SCORE_THRESHOLD = 0.005
NMS_IOU_THRESHOLD = 0.50


@dataclass(frozen=True)
class Cadence:
    window: float
    stride: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.window) or not 0 < self.stride <= self.window:
            raise ValueError("cadence requires 0 < stride <= finite window")


CADENCES = {"fine": Cadence(1.0, 0.5), "coarse": Cadence(2.0, 1.0)}


@dataclass(frozen=True)
class TemporalWindow:
    start: float
    end: float

    def __post_init__(self) -> None:
        if not 0 <= self.start < self.end or not math.isfinite(self.end):
            raise ValueError("window requires 0 <= start < finite end")


def proposal_windows(duration: float, cadence: Cadence) -> list[TemporalWindow]:
    """Start at zero and place the final full window at the source endpoint."""
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("duration must be finite and positive")
    tail = max(0.0, duration - cadence.window)
    starts = [min(tail, index * cadence.stride) for index in range(math.floor(tail / cadence.stride) + 1)]
    if tail - starts[-1] > 1e-9:
        starts.append(tail)
    else:
        starts[-1] = tail
    windows = [TemporalWindow(start, start + cadence.window) for start in starts[:-1]]
    windows.append(TemporalWindow(starts[-1], duration))
    return windows


def source_frame_indices(window: TemporalWindow, info: VideoInfo) -> tuple[int, ...]:
    """Choose the frame nearest each of eight temporal bin centers."""
    if not 0 <= window.start < window.end <= info["duration"]:
        raise ValueError(f"window {window} falls outside the source timeline")
    fps = info["fps"]
    last_frame = info["frame_count"] - 1
    first = min(last_frame, math.ceil(window.start * fps - 1e-9))
    last = min(last_frame, math.ceil(window.end * fps - 1e-9) - 1)
    if first > last:
        center = (window.start + window.end) * fps / 2
        return (max(0, min(last_frame, round(center))),) * TSM_SEGMENTS
    width = (window.end - window.start) / TSM_SEGMENTS
    return tuple(
        max(first, min(last, round((window.start + (index + 0.5) * width) * fps)))
        for index in range(TSM_SEGMENTS)
    )


def decode_source_clips(
    video_path: str | Path, info: VideoInfo, intervals: Sequence[TemporalWindow],
) -> Iterator[tuple[np.ndarray, ...]]:
    """Decode shared source indices once and preserve each interval's frame order."""
    import cv2

    frame_lists = [source_frame_indices(window, info) for window in intervals]
    if not frame_lists:
        return
    last_use = {frame: number for number, frames in enumerate(frame_lists) for frame in frames}
    targets = iter(sorted(last_use))
    next_target = next(targets, None)
    cache: dict[int, np.ndarray] = {}
    current = -1
    cap = cv2.VideoCapture(os.fspath(video_path))
    try:
        if not cap.isOpened():
            raise VideoDecodeError(f"Cannot open source video: {video_path}")
        for number, frames in enumerate(frame_lists):
            while next_target is not None and next_target <= frames[-1]:
                while current < next_target:
                    if not cap.grab():
                        raise VideoDecodeError(f"Source ended before frame {next_target}: {video_path}")
                    current += 1
                ok, bgr = cap.retrieve()
                if not ok or bgr is None or not bgr.size:
                    raise VideoDecodeError(f"Cannot retrieve source frame {current}: {video_path}")
                cache[current] = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                next_target = next(targets, None)
            clip = tuple(cache[frame] for frame in frames)
            for frame in set(frames):
                if last_use[frame] == number:
                    del cache[frame]
            yield clip
    except cv2.error as exc:
        raise VideoDecodeError(f"OpenCV failed while decoding {video_path}: {exc}") from exc
    finally:
        cap.release()


def read_class_map(path: Path, expected_count: int) -> tuple[str, ...]:
    """Read the class key at each checkpoint head index, including noncanonical keys."""
    indexed: dict[int, str] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for line, row in enumerate(csv.DictReader(handle), start=2):
            try:
                index = int(row["id"])
                key = row["key"]
                if not 0 <= index < expected_count or index in indexed or not key or key != key.strip():
                    raise ValueError("invalid or duplicate class")
            except (TypeError, ValueError, KeyError) as exc:
                raise ValueError(f"{path}:{line}: invalid class mapping") from exc
            indexed[index] = key
    if len(indexed) != expected_count or len(set(indexed.values())) != expected_count:
        raise ValueError(f"{path}: expected {expected_count} unique keys at contiguous checkpoint indices")
    return tuple(indexed[index] for index in range(expected_count))


def _softmax(logits: np.ndarray) -> np.ndarray:
    values = np.asarray(logits, dtype=np.float64)
    if not np.isfinite(values).all():
        raise ValueError("TSM logits must be finite")
    exponentials = np.exp(values - values.max(axis=1, keepdims=True))
    return exponentials / exponentials.sum(axis=1, keepdims=True)


class JointPairScorer:
    """Score taxonomy pairs which occur in the EPIC training annotations."""

    def __init__(
        self, verbs: tuple[str, ...], nouns: tuple[str, ...],
        counts: Counter[tuple[int, int]], taxonomy: Taxonomy,
    ) -> None:
        eligible: list[tuple[int, int, int]] = []
        for (verb, noun), count in counts.items():
            if not (0 <= verb < len(verbs) and 0 <= noun < len(nouns)):
                raise ValueError("training pair index falls outside the class maps")
            if count > 0 and taxonomy.has_verb(verbs[verb]) and taxonomy.has_noun(nouns[noun]):
                eligible.append((verb, noun, count))
        if not eligible:
            raise ValueError("training data has no pairs supported by the organizer taxonomy")
        verb_indices, noun_indices, frequencies = zip(*sorted(eligible), strict=True)
        self.verb_indices = np.array(verb_indices, dtype=np.intp)
        self.noun_indices = np.array(noun_indices, dtype=np.intp)
        self.prior = (np.asarray(frequencies, dtype=np.float64) / max(frequencies)) ** PAIR_PRIOR_POWER
        self.verbs = verbs
        self.nouns = nouns

    def predict(
        self, windows: Sequence[TemporalWindow], verb_logits: np.ndarray, noun_logits: np.ndarray,
        *, threshold: float = PAIR_SCORE_THRESHOLD,
    ) -> list[ActionSegment]:
        """Emit one eligible pair per window if its prior-weighted score passes the gate."""
        if not 0 < threshold <= 1:
            raise ValueError("pair score threshold must be in (0, 1]")
        count = len(windows)
        if verb_logits.shape != (count, len(self.verbs)) or noun_logits.shape != (count, len(self.nouns)):
            raise ValueError("TSM logit arrays must match the class maps and window count")
        if not count:
            return []
        joint = _softmax(verb_logits)[:, self.verb_indices] * _softmax(noun_logits)[:, self.noun_indices]
        joint *= self.prior
        actions = []
        for row, winner in enumerate(joint.argmax(axis=1)):
            confidence = float(joint[row, winner])
            if confidence >= threshold:
                window = windows[row]
                actions.append(ActionSegment(
                    self.verbs[self.verb_indices[winner]], self.nouns[self.noun_indices[winner]],
                    window.start, window.end, confidence,
                ))
        return actions


def load_joint_pair_scorer(
    train_path: Path, verb_path: Path, noun_path: Path, taxonomy: Taxonomy,
) -> JointPairScorer:
    verbs = read_class_map(verb_path, TSM_VERB_COUNT)
    nouns = read_class_map(noun_path, TSM_NOUN_COUNT)
    if verbs != taxonomy.verbs[:TSM_VERB_COUNT] or nouns != taxonomy.nouns[:TSM_NOUN_COUNT]:
        raise ValueError("EPIC class maps must match the canonical taxonomy in checkpoint index order")
    counts: Counter[tuple[int, int]] = Counter()
    with train_path.open(encoding="utf-8-sig", newline="") as handle:
        for line, row in enumerate(csv.DictReader(handle), start=2):
            try:
                verb, noun = int(row["verb_class"]), int(row["noun_class"])
                if not (0 <= verb < len(verbs) and 0 <= noun < len(nouns)):
                    raise ValueError("class index outside checkpoint heads")
            except (TypeError, ValueError, KeyError) as exc:
                raise ValueError(f"{train_path}:{line}: invalid EPIC training pair") from exc
            counts[verb, noun] += 1
    return JointPairScorer(verbs, nouns, counts, taxonomy)


def temporal_nms(actions: Sequence[ActionSegment]) -> list[ActionSegment]:
    """Suppress overlapping proposals for the same canonical pair."""
    keep: dict[tuple[str, str], list[ActionSegment]] = defaultdict(list)
    for candidate in sorted(actions, key=lambda item: (-item.confidence, item.start, item.end, item.verb, item.noun)):
        pair = candidate.verb, candidate.noun
        for previous in keep[pair]:
            intersection = min(candidate.end, previous.end) - max(candidate.start, previous.start)
            if intersection > 0:
                union = max(candidate.end, previous.end) - min(candidate.start, previous.start)
                if intersection / union >= NMS_IOU_THRESHOLD:
                    break
        else:
            keep[pair].append(candidate)
    return sorted((action for group in keep.values() for action in group), key=_timeline_key)


def _timeline_key(action: ActionSegment) -> tuple:
    return action.start, action.end, action.verb, action.noun


def merge_touching(actions: Sequence[ActionSegment]) -> list[ActionSegment]:
    """Merge overlapping or touching same-pair proposals for an optional diagnostic."""
    groups: dict[tuple[str, str], list[ActionSegment]] = defaultdict(list)
    for action in sorted(actions, key=_timeline_key):
        group = groups[action.verb, action.noun]
        if group and action.start <= group[-1].end + 1e-9:
            previous = group[-1]
            group[-1] = ActionSegment(
                action.verb, action.noun, previous.start, max(previous.end, action.end),
                max(previous.confidence, action.confidence),
            )
        else:
            group.append(action)
    return sorted((action for group in groups.values() for action in group), key=_timeline_key)


class ClipScorer(Protocol):
    def score_batch(self, clips: Sequence[Sequence[np.ndarray]]) -> tuple[np.ndarray, np.ndarray]:
        ...


@dataclass(frozen=True)
class ProposalResult:
    actions: list[ActionSegment]
    window_count: int
    accepted_before_nms: int
    decode_seconds: float
    inference_seconds: float
    proposal_seconds: float


def run_proposals(
    video_path: str | Path, info: VideoInfo, encoder: ClipScorer, scorer: JointPairScorer,
    cadence: Cadence, *, batch_size: int = 2, merge: bool = False, score_threshold: float = PAIR_SCORE_THRESHOLD,
) -> ProposalResult:
    """Decode and score source clips in bounded batches."""
    if batch_size not in (1, 2):
        raise ValueError("TSM batch size must be one or two clips")
    if not 0 < score_threshold <= 1:
        raise ValueError("pair score threshold must be in (0, 1]")
    start = time.perf_counter()
    windows = proposal_windows(info["duration"], cadence)
    actions: list[ActionSegment] = []
    decode_s = inference_s = 0.0
    with closing(decode_source_clips(video_path, info, windows)) as decoded:
        for offset in range(0, len(windows), batch_size):
            clock = time.perf_counter()
            clips = list(islice(decoded, batch_size))
            decode_s += time.perf_counter() - clock
            clock = time.perf_counter()
            verbs, nouns = encoder.score_batch(clips)
            inference_s += time.perf_counter() - clock
            del clips
            actions.extend(scorer.predict(windows[offset:offset + batch_size], verbs, nouns,
                                          threshold=score_threshold))
    accepted = len(actions)
    actions = temporal_nms(actions)
    if merge:
        actions = merge_touching(actions)
    return ProposalResult(
        actions, len(windows), accepted, decode_s, inference_s,
        max(0.0, time.perf_counter() - start - decode_s - inference_s),
    )
