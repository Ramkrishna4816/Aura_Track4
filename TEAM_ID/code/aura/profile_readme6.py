"""Six-key student-README profile (provisional active profile).

Source: TEAM_README.md sections 3-4 (the README the organizers shipped with
manifest.csv and supported_classes.json). Field names follow its example:
team_id, video_id, duration_sec, label{name,score}, actions[{segment,verb,noun,score}],
highlights[{segment}].
"""
from __future__ import annotations

import math
from typing import Any

from . import config
from .models import VideoPrediction
from .serialization import (LOCAL_POLICY, Collector, SerializationProfile, ValidationReport,
                            has_excess_decimals, round_time)
from .normalize import as_real
from .taxonomy import Taxonomy

B3, B4 = "README section 3", "README section 4"


class Readme6Profile(SerializationProfile):
    name = "readme6"

    TOP_KEYS = ("team_id", "video_id", "duration_sec", "label", "actions", "highlights")
    LABEL_KEYS = ("name", "score")
    ACTION_KEYS = ("segment", "verb", "noun", "score")
    HIGHLIGHT_KEYS = ("segment",)

    FIELD_MAP = {
        "VideoContext.team_id": "team_id",
        "VideoContext.video_id": "video_id",
        "VideoContext.duration_sec": "duration_sec",
        "Label.name": "label.name",
        "Label.score": "label.score",
        "ActionSegment.verb": "actions[].verb",
        "ActionSegment.noun": "actions[].noun",
        "ActionSegment.start": "actions[].segment[0]",
        "ActionSegment.end": "actions[].segment[1]",
        "ActionSegment.confidence": "actions[].score",
        "Highlight.start": "highlights[].segment[0]",
        "Highlight.end": "highlights[].segment[1]",
    }
    OMISSIONS = {
        "Highlight.importance": (
            "README highlight objects contain only 'segment'; importance is used "
            "internally to select highlights and is intentionally not emitted."
        ),
    }

    def build(self, prediction: VideoPrediction) -> dict:
        d = config.README6_TIME_DECIMALS
        ctx = prediction.context
        return {
            "team_id": ctx.team_id,
            "video_id": ctx.video_id,
            "duration_sec": round_time(ctx.duration_sec, d),
            "label": {"name": prediction.label.name, "score": prediction.label.score},
            "actions": [
                {
                    "segment": [round_time(a.start, d), round_time(a.end, d)],
                    "verb": a.verb,
                    "noun": a.noun,
                    "score": a.confidence,
                }
                for a in prediction.actions
            ],
            "highlights": [
                {"segment": [round_time(h.start, d), round_time(h.end, d)]}
                for h in prediction.highlights
            ],
        }

    # -- validation -----------------------------------------------------------------

    def _segment(self, c: Collector, value: Any, path: str, upper: float | None,
                 basis: str) -> tuple[float, float] | None:
        if not isinstance(value, list) or len(value) != 2:
            c.error("bad_segment", path, f"must be a list [start, end], got {value!r}", basis)
            return None
        start = c.real(value[0], f"{path}[0]", basis)
        end = c.real(value[1], f"{path}[1]", basis)
        if start is None or end is None:
            return None
        if start < 0 or end <= start or (upper is not None and end > upper + config.TIME_EPSILON):
            bound = "" if upper is None else f" <= duration_sec + {config.README6_SEGMENT_END_TOLERANCE_S}"
            c.error("bad_interval", path, f"requires 0 <= start < end{bound}; got [{start}, {end}]", basis)
            return None
        for index, number in enumerate((start, end)):
            if has_excess_decimals(number, config.README6_TIME_DECIMALS):
                c.warning("too_many_decimals", f"{path}[{index}]",
                          f"more than {config.README6_TIME_DECIMALS} decimal places: {number}", B3)
        return start, end

    def validate(self, data: Any, *, reference_duration_sec: float | None = None,
                 taxonomy: Taxonomy | None = None,
                 budget_ratio: float = config.HIGHLIGHT_BUDGET_RATIO,
                 allow_short_highlights: bool = False) -> ValidationReport:
        ratio = as_real(budget_ratio)
        if ratio is None or not 0 < ratio <= 1:
            raise ValueError(f"budget_ratio must be in (0, 1], got {budget_ratio!r}")
        reference = None
        if reference_duration_sec is not None:
            reference = as_real(reference_duration_sec)
            if reference is None or not math.isfinite(reference) or reference <= 0:
                raise ValueError(f"reference_duration_sec must be finite and > 0, got {reference_duration_sec!r}")

        c = Collector()
        if not c.exact_keys(data, self.TOP_KEYS, "$", B3):
            return c.report()

        if "team_id" in data:
            c.text(data["team_id"], "team_id", B3)
        if "video_id" in data:
            c.text(data["video_id"], "video_id", B3)

        duration = None
        if "duration_sec" in data:
            duration = c.real(data["duration_sec"], "duration_sec", B3)
            if duration is not None and duration <= 0:
                c.error("non_positive_duration", "duration_sec", f"must be > 0, got {duration}", B3)
                duration = None
        if duration is not None and reference is not None and abs(duration - reference) > 0.5 + config.TIME_EPSILON:
            c.error("duration_mismatch", "duration_sec",
                    f"{duration} differs from the reference duration {reference} by more than 0.5 s", B3)
        upper = None if duration is None else duration + config.README6_SEGMENT_END_TOLERANCE_S

        if "label" in data and c.exact_keys(data["label"], self.LABEL_KEYS, "label", B3):
            label = data["label"]
            name = c.text(label["name"], "label.name", B3) if "name" in label else None
            if name is not None and taxonomy is not None and not taxonomy.has_label(name):
                c.error("label_not_in_taxonomy", "label.name",
                        f"{name!r} is not a label in the supplied taxonomy", f"{B3} + {LOCAL_POLICY}")
            if "score" in label:
                c.unit(label["score"], "label.score", B3)

        if "actions" in data:
            self._validate_actions(c, data["actions"], upper, taxonomy)
        if "highlights" in data:
            budget_duration = duration if reference is None else reference
            self._validate_highlights(c, data["highlights"], upper, budget_duration, ratio, allow_short_highlights)
        c.strict_json_check(data)
        return c.report()

    def _validate_actions(self, c: Collector, actions: Any, upper: float | None,
                          taxonomy: Taxonomy | None) -> None:
        if not isinstance(actions, list):
            c.error("not_array", "actions", f"must be an array, got {type(actions).__name__}", B3)
            return
        if len(actions) > config.README6_MAX_ACTIONS:
            c.error("too_many_actions", "actions",
                    f"{len(actions)} items; at most {config.README6_MAX_ACTIONS} allowed", B3)
        for i, item in enumerate(actions):
            path = f"actions[{i}]"
            if not c.exact_keys(item, self.ACTION_KEYS, path, B3):
                continue
            if "segment" in item:
                self._segment(c, item["segment"], f"{path}.segment", upper, B3)
            for key, check in (("verb", "has_verb"), ("noun", "has_noun")):
                if key not in item:
                    continue
                value = c.text(item[key], f"{path}.{key}", B3)
                if value is not None and taxonomy is not None and not getattr(taxonomy, check)(value):
                    c.error(f"{key}_not_in_taxonomy", f"{path}.{key}",
                            f"{value!r} is not in the supplied taxonomy", LOCAL_POLICY)
            if "score" in item:
                c.unit(item["score"], f"{path}.score", B3)

    def _validate_highlights(self, c: Collector, highlights: Any, upper: float | None,
                             duration: float | None, ratio: float, allow_short_highlights: bool) -> None:
        if not isinstance(highlights, list):
            c.error("not_array", "highlights", f"must be an array, got {type(highlights).__name__}", B3)
            return
        if not highlights:
            c.error("no_highlights", "highlights", "at least 1 highlight is required", B3)
            return
        segments: list[tuple[int, float, float]] = []
        for i, item in enumerate(highlights):
            path = f"highlights[{i}]"
            if c.exact_keys(item, self.HIGHLIGHT_KEYS, path, B3) and "segment" in item:
                seg = self._segment(c, item["segment"], f"{path}.segment", upper, B3)
                if seg is not None:
                    segments.append((i, seg[0], seg[1]))
        for (_, s0, e0), (i1, s1, _) in zip(segments, segments[1:]):
            path = f"highlights[{i1}].segment"
            if s1 < s0:
                c.error("highlights_unsorted", path, "highlights must be chronologically sorted", B3)
            elif s1 < e0 - config.TIME_EPSILON:
                c.error("highlight_overlap", path, "overlaps the previous highlight", B3)
            elif abs(s1 - e0) <= config.TIME_EPSILON:
                c.warning("highlight_touching", path,
                          "touches the previous highlight; README says 'strictly non-overlapping'/'zero overlap'", B3)
        minimum = config.README6_MIN_HIGHLIGHT_SEGMENT_S
        lengths = [(i, e - s) for i, s, e in segments]
        if segments and not any(n >= minimum - config.TIME_EPSILON for _, n in lengths):
            message = f"student README requires at least one segment >= {minimum} s"
            if allow_short_highlights:
                c.warning("no_long_highlight", "highlights", f"{message}. Short highlight policy applied.",
                          f"{B3} + {LOCAL_POLICY}")
            else:
                c.error("no_long_highlight", "highlights", message, B3)
        for i, n in lengths:
            if n < minimum - config.TIME_EPSILON:
                c.warning("short_highlight", f"highlights[{i}].segment",
                          f"{n:.2f} s < {minimum} s (README: ignored during scoring)", B4)
        if duration is not None:
            total = sum(n for _, n in lengths)
            if total > ratio * duration + config.TIME_EPSILON:
                c.warning("over_budget", "highlights",
                          f"total {total:.2f} s exceeds {ratio:.0%} of duration ({ratio * duration:.2f} s); "
                          "README treats the budget as a soft target", B3)
