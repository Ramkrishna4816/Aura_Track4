"""Taxonomy (supported_classes.json) loading and structural validation.

Structural checks only: required lists exist, hold unique non-empty strings, and
carry no padding whitespace. Sizes and specific class names are NOT encoded here;
whatever the organizer file contains is what gets used.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REQUIRED_LISTS = ("labels", "verbs", "nouns")


class TaxonomyError(ValueError):
    """The taxonomy file is missing, unreadable, or structurally invalid."""


@dataclass(frozen=True)
class Taxonomy:
    """Ordered class lists (file order preserved) with O(1) membership checks."""

    version: str | None
    labels: tuple[str, ...]
    verbs: tuple[str, ...]
    nouns: tuple[str, ...]
    label_set: frozenset = field(init=False, repr=False, compare=False)
    verb_set: frozenset = field(init=False, repr=False, compare=False)
    noun_set: frozenset = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "label_set", frozenset(self.labels))
        object.__setattr__(self, "verb_set", frozenset(self.verbs))
        object.__setattr__(self, "noun_set", frozenset(self.nouns))

    def has_label(self, name: object) -> bool:
        return isinstance(name, str) and name in self.label_set

    def has_verb(self, name: object) -> bool:
        return isinstance(name, str) and name in self.verb_set

    def has_noun(self, name: object) -> bool:
        return isinstance(name, str) and name in self.noun_set


def _string_list(data: dict, key: str) -> tuple[str, ...]:
    if key not in data:
        raise TaxonomyError(f"missing required key {key!r}")
    items = data[key]
    if not isinstance(items, list):
        raise TaxonomyError(f"{key!r} must be a list, got {type(items).__name__}")
    if not items:
        raise TaxonomyError(f"{key!r} must not be empty")
    seen: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, str):
            raise TaxonomyError(f"{key}[{index}] must be a string, got {item!r}")
        if not item:
            raise TaxonomyError(f"{key}[{index}] must not be empty")
        if item != item.strip():
            raise TaxonomyError(f"{key}[{index}] has leading/trailing whitespace: {item!r}")
        if item in seen:
            raise TaxonomyError(f"{key} contains a duplicate entry: {item!r}")
        seen.add(item)
    return tuple(items)


def parse_taxonomy(data: Any) -> Taxonomy:
    """Validate already-parsed JSON and build a Taxonomy. Extra keys are ignored."""
    if not isinstance(data, dict):
        raise TaxonomyError(f"taxonomy must be a JSON object, got {type(data).__name__}")
    version = data.get("version")
    if version is not None and (not isinstance(version, str) or not version.strip()):
        raise TaxonomyError(f"'version' must be a non-empty string when present, got {version!r}")
    lists = {key: _string_list(data, key) for key in REQUIRED_LISTS}
    return Taxonomy(version, lists["labels"], lists["verbs"], lists["nouns"])


def _reject_constant(name: str) -> None:
    raise ValueError(f"non-finite JSON constant {name!r} is not allowed")


def load_taxonomy(path: "str | Path") -> Taxonomy:
    """Load and validate a taxonomy file (UTF-8, optional BOM)."""
    target = Path(path)
    try:
        text = target.read_bytes().decode("utf-8-sig")
        data = json.loads(text, parse_constant=_reject_constant)
    except OSError as exc:
        raise TaxonomyError(f"cannot read taxonomy file {target}: {exc}") from exc
    except (UnicodeDecodeError, ValueError) as exc:
        raise TaxonomyError(f"invalid taxonomy JSON in {target}: {exc}") from exc
    return parse_taxonomy(data)


def bundled_taxonomy_path() -> Path:
    """Location of the unmodified organizer file shipped inside the submission."""
    return Path(__file__).resolve().parent.parent / "resources" / "supported_classes.json"


def load_bundled_taxonomy() -> Taxonomy:
    return load_taxonomy(bundled_taxonomy_path())
