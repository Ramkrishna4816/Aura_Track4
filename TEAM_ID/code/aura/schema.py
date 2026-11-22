"""Output construction and local schema validation.

The key layout below is the ASSUMED schema inherited from the starter and has
NOT been checked against the organizer's kit. It is unchanged in this revision.
"""
from __future__ import annotations

import json
import math
from typing import Any, Collection, Sequence

from . import config
from .models import ActionSegment, Highlight
from .normalize import as_real

TOP_LEVEL_KEYS = frozenset({"video_id", "label", "actions", "highlights"})
ACTION_KEYS = frozenset({"verb", "noun", "start", "end"})
HIGHLIGHT_KEYS = frozenset({"start", "end", "importance"})


class SchemaValidationError(ValueError):
    """The output (or an input to build it) violates the local schema."""


def _require_str(value: Any, what: str) -> str:
    if not isinstance(value, str):
        raise SchemaValidationError(f"{what} must be a string, got {value!r}")
    return value


def _round_time(value: Any, what: str) -> float:
    number = as_real(value)
    if number is None:
        raise SchemaValidationError(f"{what} must be a number, got {value!r}")
    return round(number, config.TIME_PRECISION_DECIMALS)


def _importance(value: Any, what: str) -> float:
    number = as_real(value)
    if number is None:
        raise SchemaValidationError(f"{what} must be a number, got {value!r}")
    return number


def build_output(
    video_id: str,
    label: str,
    actions: Sequence[ActionSegment],
    highlights: Sequence[Highlight],
) -> dict:
    """Assemble the output dict. Strings are never coerced (a None verb is an
    error, not the text "None"); times are rounded to the configured precision."""
    return {
        "video_id": _require_str(video_id, "video_id"),
        "label": _require_str(label, "label"),
        "actions": [
            {
                "verb": _require_str(a.verb, f"actions[{i}].verb"),
                "noun": _require_str(a.noun, f"actions[{i}].noun"),
                "start": _round_time(a.start, f"actions[{i}].start"),
                "end": _round_time(a.end, f"actions[{i}].end"),
            }
            for i, a in enumerate(actions)
        ],
        "highlights": [
            {
                "start": _round_time(h.start, f"highlights[{i}].start"),
                "end": _round_time(h.end, f"highlights[{i}].end"),
                "importance": _importance(h.importance, f"highlights[{i}].importance"),
            }
            for i, h in enumerate(highlights)
        ],
    }


def _check_number(item: dict, key: str, where: str) -> float:
    number = as_real(item[key])
    if number is None:
        raise SchemaValidationError(f"{where}.{key} must be a number, got {item[key]!r}")
    if not math.isfinite(number):
        raise SchemaValidationError(f"{where}.{key} must be finite, got {number}")
    return number


def _check_interval(item: Any, keys: frozenset, where: str, duration: float) -> tuple[float, float]:
    if not isinstance(item, dict):
        raise SchemaValidationError(f"{where} must be an object")
    if set(item.keys()) != keys:
        raise SchemaValidationError(f"{where} keys must be exactly {sorted(keys)}")
    start = _check_number(item, "start", where)
    end = _check_number(item, "end", where)
    if start < 0 or end <= start or end > duration + config.TIME_EPSILON:
        raise SchemaValidationError(
            f"{where} has an invalid interval [{start}, {end}] for duration {duration}")
    return start, end


def _check_text(item: dict, key: str, where: str) -> str:
    value = item[key]
    if not isinstance(value, str) or not value.strip():
        raise SchemaValidationError(f"{where}.{key} must be a non-empty string, got {value!r}")
    return value


def validate_output(
    data: Any,
    duration: float,
    budget_ratio: float = config.HIGHLIGHT_BUDGET_RATIO,
    *,
    allowed_labels: Collection[str] | None = None,
    allowed_verbs: Collection[str] | None = None,
    allowed_nouns: Collection[str] | None = None,
) -> None:
    """Raise SchemaValidationError (a ValueError) on any violation.

    The allowed_* collections are optional hooks for the organizer's taxonomy;
    None skips membership checks. No classes are defined or assumed here.
    """
    dur = as_real(duration)
    if dur is None or not math.isfinite(dur) or dur <= 0:
        raise SchemaValidationError(f"duration must be finite and positive, got {duration!r}")
    ratio = as_real(budget_ratio)
    if ratio is None or not math.isfinite(ratio) or not 0 < ratio <= 1:
        raise SchemaValidationError(f"budget_ratio must be in (0, 1], got {budget_ratio!r}")

    if not isinstance(data, dict):
        raise SchemaValidationError("Output must be a JSON object")
    if set(data.keys()) != TOP_LEVEL_KEYS:
        raise SchemaValidationError(f"Output keys must be exactly {sorted(TOP_LEVEL_KEYS)}")
    _check_text(data, "video_id", "output")
    label = _check_text(data, "label", "output")
    if allowed_labels is not None and label not in allowed_labels:
        raise SchemaValidationError(f"label {label!r} is not in the allowed label set")
    if not isinstance(data["actions"], list) or not isinstance(data["highlights"], list):
        raise SchemaValidationError("actions and highlights must be lists")

    for i, item in enumerate(data["actions"]):
        where = f"actions[{i}]"
        _check_interval(item, ACTION_KEYS, where, dur)
        verb = _check_text(item, "verb", where)
        noun = _check_text(item, "noun", where)
        if allowed_verbs is not None and verb not in allowed_verbs:
            raise SchemaValidationError(f"{where}.verb {verb!r} is not in the allowed verb set")
        if allowed_nouns is not None and noun not in allowed_nouns:
            raise SchemaValidationError(f"{where}.noun {noun!r} is not in the allowed noun set")

    total = 0.0
    prev: tuple[float, float] | None = None
    for i, item in enumerate(data["highlights"]):
        where = f"highlights[{i}]"
        start, end = _check_interval(item, HIGHLIGHT_KEYS, where, dur)
        score = _check_number(item, "importance", where)
        if not 0.0 <= score <= 1.0:
            raise SchemaValidationError(f"{where}.importance must be in [0, 1], got {score}")
        if prev is not None:
            if start < prev[0]:
                raise SchemaValidationError(f"{where} is not sorted by start time")
            if start < prev[1] - config.TIME_EPSILON:
                raise SchemaValidationError(f"{where} overlaps the previous highlight")
        prev = (start, end)
        total += end - start
    if total > dur * ratio + config.TIME_EPSILON:
        raise SchemaValidationError(
            f"Highlight duration {total:.3f}s exceeds the budget {dur * ratio:.3f}s")

    try:
        json.dumps(data, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise SchemaValidationError(f"Output is not strict-JSON serializable: {exc}") from exc
