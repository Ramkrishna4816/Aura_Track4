"""Four-key slide profile (available via AURA_PROFILE=slide4).

Source: the output example on slide 22 of the challenge presentation:
video_id, label (a plain string), actions[{verb,noun,start,end}],
highlights[{start,end,importance}]. The slide shows an example only; every rule
below that the slide does not state is marked as local policy or reported as a
warning. Kept so the output format can be switched by changing
`config.ACTIVE_PROFILE` without touching the pipeline.
"""
from __future__ import annotations

import math
from typing import Any

from . import config
from .models import VideoPrediction
from .normalize import as_real
from .serialization import (LOCAL_POLICY, Collector, SerializationProfile, ValidationReport,
                            round_time)
from .taxonomy import Taxonomy

S22 = "slide 22 example"
UNSTATED = f"{LOCAL_POLICY} (slide is silent)"


class Slide4Profile(SerializationProfile):
    name = "slide4"

    TOP_KEYS = ("video_id", "label", "actions", "highlights")
    ACTION_KEYS = ("verb", "noun", "start", "end")
    HIGHLIGHT_KEYS = ("start", "end", "importance")

    FIELD_MAP = {
        "VideoContext.video_id": "video_id",
        "Label.name": "label",
        "ActionSegment.verb": "actions[].verb",
        "ActionSegment.noun": "actions[].noun",
        "ActionSegment.start": "actions[].start",
        "ActionSegment.end": "actions[].end",
        "Highlight.start": "highlights[].start",
        "Highlight.end": "highlights[].end",
        "Highlight.importance": "highlights[].importance",
    }
    OMISSIONS = {
        "VideoContext.team_id": "the slide 22 example has no team_id key",
        "VideoContext.duration_sec": "the slide 22 example has no duration_sec key",
        "Label.score": "the slide 22 label is a plain string, not an object with a score",
        "ActionSegment.confidence": "the slide 22 action objects carry no score",
    }

    def build(self, prediction: VideoPrediction) -> dict:
        d = config.SLIDE4_TIME_DECIMALS
        return {
            "video_id": prediction.context.video_id,
            "label": prediction.label.name,
            "actions": [
                {
                    "verb": a.verb,
                    "noun": a.noun,
                    "start": round_time(a.start, d),
                    "end": round_time(a.end, d),
                }
                for a in prediction.actions
            ],
            "highlights": [
                {
                    "start": round_time(h.start, d),
                    "end": round_time(h.end, d),
                    "importance": h.importance,
                }
                for h in prediction.highlights
            ],
        }

    def _interval(self, c: Collector, item: dict, path: str, upper: float | None) -> tuple[float, float] | None:
        if "start" not in item or "end" not in item:
            return None
        start = c.real(item["start"], f"{path}.start", S22)
        end = c.real(item["end"], f"{path}.end", S22)
        if start is None or end is None:
            return None
        if start < 0 or end <= start or (upper is not None and end > upper + config.TIME_EPSILON):
            c.error("bad_interval", path, f"requires 0 <= start < end (<= video duration); got [{start}, {end}]",
                    UNSTATED)
            return None
        return start, end

    def validate(self, data: Any, *, reference_duration_sec: float | None = None,
                 taxonomy: Taxonomy | None = None,
                 budget_ratio: float = config.HIGHLIGHT_BUDGET_RATIO,
                 allow_short_highlights: bool = False) -> ValidationReport:
        ratio = as_real(budget_ratio)
        if ratio is None or not 0 < ratio <= 1:
            raise ValueError(f"budget_ratio must be in (0, 1], got {budget_ratio!r}")
        duration = None
        if reference_duration_sec is not None:
            duration = as_real(reference_duration_sec)
            if duration is None or not math.isfinite(duration) or duration <= 0:
                raise ValueError(f"reference_duration_sec must be finite and > 0, got {reference_duration_sec!r}")

        c = Collector()
        if not c.exact_keys(data, self.TOP_KEYS, "$", S22):
            return c.report()
        if duration is None:
            c.warning("duration_unavailable", "$",
                      "this schema has no duration field and no reference duration was given; "
                      "time ranges were not checked against the video length", UNSTATED)

        if "video_id" in data:
            c.text(data["video_id"], "video_id", S22)
        if "label" in data:
            name = c.text(data["label"], "label", S22)
            if name is not None and taxonomy is not None and not taxonomy.has_label(name):
                c.error("label_not_in_taxonomy", "label",
                        f"{name!r} is not a label in the supplied taxonomy", LOCAL_POLICY)

        actions = data["actions"] if "actions" in data else []
        if not isinstance(actions, list):
            c.error("not_array", "actions", f"must be an array, got {type(actions).__name__}", S22)
            actions = []
        for i, item in enumerate(actions):
            path = f"actions[{i}]"
            if not c.exact_keys(item, self.ACTION_KEYS, path, S22):
                continue
            self._interval(c, item, path, duration)
            for key, check in (("verb", "has_verb"), ("noun", "has_noun")):
                if key in item:
                    value = c.text(item[key], f"{path}.{key}", S22)
                    if value is not None and taxonomy is not None and not getattr(taxonomy, check)(value):
                        c.error(f"{key}_not_in_taxonomy", f"{path}.{key}",
                                f"{value!r} is not in the supplied taxonomy", LOCAL_POLICY)

        highlights = data["highlights"] if "highlights" in data else []
        if not isinstance(highlights, list):
            c.error("not_array", "highlights", f"must be an array, got {type(highlights).__name__}", S22)
            highlights = []
        spans: list[tuple[int, float, float]] = []
        for i, item in enumerate(highlights):
            path = f"highlights[{i}]"
            if not c.exact_keys(item, self.HIGHLIGHT_KEYS, path, S22):
                continue
            span = self._interval(c, item, path, duration)
            if span is not None:
                spans.append((i, span[0], span[1]))
            if "importance" in item:
                score = c.real(item["importance"], f"{path}.importance", S22)
                if score is not None and not 0.0 <= score <= 1.0:
                    c.warning("importance_range_unstated", f"{path}.importance",
                              f"{score} is outside [0, 1]; the slide shows 0.93 but states no range", UNSTATED)
        for (_, s0, e0), (i1, s1, _) in zip(spans, spans[1:]):
            if s1 < s0 or s1 < e0 - config.TIME_EPSILON:
                c.warning("highlights_unordered_or_overlapping", f"highlights[{i1}]",
                          "highlights should be sorted and non-overlapping (slide: 'keep original footage')", UNSTATED)
        if duration is not None and spans:
            total = sum(e - s for _, s, e in spans)
            if total > ratio * duration + config.TIME_EPSILON:
                c.warning("over_budget", "highlights",
                          f"total {total:.2f} s exceeds {ratio:.0%} of duration; slide says 'aim for ~15%'", S22)
        c.strict_json_check(data)
        return c.report()
