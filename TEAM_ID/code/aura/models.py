"""Plain dataclasses shared between pipeline stages. No behavior, no I/O."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence, Union

_ACTION_FIELDS = ("verb", "noun", "start", "end", "confidence")


@dataclass(frozen=True)
class ActionSegment:
    """One predicted verb-noun action with a temporal extent (seconds).

    Values are NOT validated here: a recognizer may emit NaN or out-of-range
    numbers, and `normalize.normalize_actions` is the stage that checks them.
    """

    verb: str
    noun: str
    start: float
    end: float
    confidence: float

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ActionSegment":
        """Build from a dict-like prediction. Missing fields raise ValueError;
        values are passed through unchanged (never coerced or defaulted)."""
        if not isinstance(data, Mapping):
            raise ValueError(f"expected a mapping, got {type(data).__name__}")
        missing = [k for k in _ACTION_FIELDS if k not in data]
        if missing:
            raise ValueError(f"missing field(s): {', '.join(missing)}")
        return cls(**{k: data[k] for k in _ACTION_FIELDS})


@dataclass(frozen=True)
class Highlight:
    """A highlight segment (seconds) with an importance score in [0, 1]."""

    start: float
    end: float
    importance: float


RawAction = Union[ActionSegment, Mapping[str, Any]]


@dataclass(frozen=True)
class RecognitionResult:
    """What a recognizer returns for one video (organizer-dependent source)."""

    video_id: str
    actions: Sequence[RawAction]


# --- Schema-independent prediction container -----------------------------------
# These types use neutral internal names (`confidence`, `importance`) and know
# nothing about output field names. Serialization profiles map them to a schema.

@dataclass(frozen=True)
class VideoContext:
    """Identity and metadata of the video being summarized (seconds)."""

    team_id: str
    video_id: str
    duration_sec: float


@dataclass(frozen=True)
class Label:
    """Video-level label with a confidence in [0, 1]."""

    name: str
    score: float


@dataclass(frozen=True)
class VideoPrediction:
    """Everything the pipeline predicts for one video, before serialization."""

    context: VideoContext
    label: Label
    actions: Sequence[ActionSegment]
    highlights: Sequence[Highlight]
