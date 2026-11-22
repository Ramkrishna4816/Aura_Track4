"""Schema-independent serialization layer.

The pipeline produces a `VideoPrediction` (neutral internal names). A
*serialization profile* maps it to one concrete output schema and validates the
result. Profiles live in their own modules; the active one is chosen by
`config.ACTIVE_PROFILE`. Nothing here emits more than one format.

Every internal field must either be emitted or be listed in the profile's
OMISSIONS with a reason, so nothing is dropped silently. This is enforced when a
profile is loaded (see `check_field_coverage`).

Validation severities:
  ERROR   - a rule the source document states as required, or an explicit local
            policy (the issue's `basis` says which). Serialization refuses.
  WARNING - a rule stated as soft/advisory, ambiguous, or unstated. Reported,
            never silently ignored, but does not block serialization.
The official validator was not supplied; none of this claims its behavior.
"""
from __future__ import annotations

import dataclasses
import importlib
import json
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Collection, Mapping

from . import config
from .io_utils import dumps_output
from .models import ActionSegment, Highlight, Label, VideoContext, VideoPrediction
from .normalize import as_real
from .taxonomy import Taxonomy

LOCAL_POLICY = "local policy"

# name -> (module, class); modules are imported lazily to avoid import cycles.
_PROFILES: Mapping[str, tuple[str, str]] = {
    "readme6": ("profile_readme6", "Readme6Profile"),
    "slide4": ("profile_slide4", "Slide4Profile"),
}


class Severity(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class ValidationIssue:
    severity: Severity
    code: str
    path: str
    message: str
    basis: str

    def format(self) -> str:
        return f"{self.severity.value.upper()} [{self.code}] {self.path}: {self.message} (basis: {self.basis})"


@dataclass(frozen=True)
class ValidationReport:
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity is Severity.ERROR)

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity is Severity.WARNING)

    @property
    def ok(self) -> bool:
        return not self.errors

    def codes(self, severity: Severity | None = None) -> list[str]:
        return [i.code for i in self.issues if severity is None or i.severity is severity]

    def format(self) -> str:
        return "\n".join(i.format() for i in self.issues) or "no issues"


class ProfileValidationError(ValueError):
    """Serialization refused because validation found errors."""

    def __init__(self, report: ValidationReport) -> None:
        super().__init__("output failed validation:\n" + report.format())
        self.report = report


class ProfileDefinitionError(RuntimeError):
    """A profile does not account for every internal field."""


@dataclass(frozen=True)
class SerializedOutput:
    text: str                 # strict JSON (no NaN/Infinity), trailing newline
    data: dict                # the object that was serialized
    report: ValidationReport  # includes warnings


# --- helpers shared by profiles --------------------------------------------------

def round_time(value: Any, decimals: int) -> Any:
    """Round finite real numbers; return anything else unchanged so the validator
    (not the builder) reports it with a precise path."""
    number = as_real(value)
    if number is None or not math.isfinite(number):
        return value
    return round(number, decimals)


def has_excess_decimals(value: float, decimals: int) -> bool:
    return abs(value - round(value, decimals)) > 1e-9


def internal_fields() -> frozenset[str]:
    """Leaf internal fields every profile must account for, as 'Class.field'."""
    return frozenset(
        f"{cls.__name__}.{f.name}"
        for cls in (VideoContext, Label, ActionSegment, Highlight)
        for f in dataclasses.fields(cls)
    )


class Collector:
    """Accumulates validation issues with consistent paths and bases."""

    def __init__(self) -> None:
        self.issues: list[ValidationIssue] = []

    def error(self, code: str, path: str, message: str, basis: str) -> None:
        self.issues.append(ValidationIssue(Severity.ERROR, code, path, message, basis))

    def warning(self, code: str, path: str, message: str, basis: str) -> None:
        self.issues.append(ValidationIssue(Severity.WARNING, code, path, message, basis))

    def real(self, value: Any, path: str, basis: str) -> float | None:
        number = as_real(value)
        if number is None:
            self.error("not_a_number", path, f"must be a number, got {value!r}", basis)
            return None
        if not math.isfinite(number):
            self.error("non_finite", path, f"must be finite, got {number}", basis)
            return None
        return number

    def unit(self, value: Any, path: str, basis: str) -> float | None:
        number = self.real(value, path, basis)
        if number is not None and not 0.0 <= number <= 1.0:
            self.error("out_of_range", path, f"must be in [0, 1], got {number}", basis)
            return None
        return number

    def text(self, value: Any, path: str, basis: str) -> str | None:
        if not isinstance(value, str) or not value.strip():
            self.error("bad_string", path, f"must be a non-empty string, got {value!r}", basis)
            return None
        return value

    def exact_keys(self, obj: Any, expected: Collection[str], path: str, basis: str) -> bool:
        """True if `obj` is a dict (key problems are reported but validation continues)."""
        if not isinstance(obj, dict):
            self.error("not_object", path, f"must be an object, got {type(obj).__name__}", basis)
            return False
        for key in sorted(set(expected) - set(obj)):
            self.error("missing_key", f"{path}.{key}", "required key is missing", basis)
        for key in sorted(set(obj) - set(expected)):
            self.error("unexpected_key", f"{path}.{key}", "key is not part of this profile", LOCAL_POLICY)
        return True

    def strict_json_check(self, data: Any) -> None:
        """Last gate: only meaningful when no earlier error was found."""
        if any(i.severity is Severity.ERROR for i in self.issues):
            return
        try:
            json.dumps(data, allow_nan=False)
        except (TypeError, ValueError) as exc:
            self.error("not_strict_json", "$", f"not serializable as strict JSON: {exc}", LOCAL_POLICY)

    def report(self) -> ValidationReport:
        return ValidationReport(tuple(self.issues))


# --- profile base class ------------------------------------------------------------

class SerializationProfile(ABC):
    """Maps a VideoPrediction to one output schema and validates it."""

    name: ClassVar[str]
    #: internal field ("Class.field") -> where it appears in the output
    FIELD_MAP: ClassVar[Mapping[str, str]]
    #: internal field -> reason it is intentionally not emitted by this profile
    OMISSIONS: ClassVar[Mapping[str, str]]

    @abstractmethod
    def build(self, prediction: VideoPrediction) -> dict:
        """Pure mapping. Never raises on bad values; the validator reports them."""

    @abstractmethod
    def validate(
        self,
        data: Any,
        *,
        reference_duration_sec: float | None = None,
        taxonomy: Taxonomy | None = None,
        budget_ratio: float = config.HIGHLIGHT_BUDGET_RATIO,
        allow_short_highlights: bool = False,
    ) -> ValidationReport:
        """`reference_duration_sec` is an independent duration (decoded video or
        manifest) used for cross-checks and, where the schema has no duration
        field, for range checks."""

    def serialize_with_report(
        self,
        prediction: VideoPrediction,
        *,
        taxonomy: Taxonomy | None = None,
        budget_ratio: float = config.HIGHLIGHT_BUDGET_RATIO,
        allow_short_highlights: bool = False,
    ) -> SerializedOutput:
        data = self.build(prediction)
        report = self.validate(
            data,
            reference_duration_sec=prediction.context.duration_sec,
            taxonomy=taxonomy,
            budget_ratio=budget_ratio,
            allow_short_highlights=allow_short_highlights,
        )
        if not report.ok:
            raise ProfileValidationError(report)
        return SerializedOutput(dumps_output(data) + "\n", data, report)

    def serialize(self, prediction: VideoPrediction, **kwargs: Any) -> str:
        return self.serialize_with_report(prediction, **kwargs).text


def check_field_coverage(profile: SerializationProfile) -> None:
    """Every internal field is emitted xor intentionally omitted (with a reason)."""
    mapped, omitted = set(profile.FIELD_MAP), set(profile.OMISSIONS)
    expected = internal_fields()
    problems = []
    if mapped & omitted:
        problems.append(f"both emitted and omitted: {sorted(mapped & omitted)}")
    if expected - (mapped | omitted):
        problems.append(f"unaccounted internal fields: {sorted(expected - (mapped | omitted))}")
    if (mapped | omitted) - expected:
        problems.append(f"unknown fields listed: {sorted((mapped | omitted) - expected)}")
    if not all(reason.strip() for reason in profile.OMISSIONS.values()):
        problems.append("every omission needs a non-empty reason")
    if problems:
        raise ProfileDefinitionError(f"profile {profile.name!r}: " + "; ".join(problems))


# --- registry ------------------------------------------------------------------------

def available_profiles() -> tuple[str, ...]:
    return tuple(sorted(_PROFILES))


def get_profile(name: str) -> SerializationProfile:
    if name not in _PROFILES:
        raise ValueError(f"unknown serialization profile {name!r}; available: {available_profiles()}")
    module_name, class_name = _PROFILES[name]
    module = importlib.import_module(f"{__package__}.{module_name}")
    profile = getattr(module, class_name)()
    check_field_coverage(profile)
    return profile


def active_profile() -> SerializationProfile:
    """The single profile selected by config.ACTIVE_PROFILE (read at call time)."""
    return get_profile(config.ACTIVE_PROFILE)


def serialize_active(prediction: VideoPrediction, **kwargs: Any) -> str:
    return active_profile().serialize(prediction, **kwargs)
