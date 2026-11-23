#!/usr/bin/env python3
"""Independently check Track 4 six-key predictions against the student kit."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent
CODE = ROOT / "code" if (ROOT / "code" / "aura").is_dir() else ROOT / "TEAM_ID" / "code"
sys.path.insert(0, str(CODE))

from aura.manifest import BUNDLED_MANIFEST_PATH, ManifestEntry, load_manifest
from aura.taxonomy import Taxonomy, bundled_taxonomy_path, load_taxonomy


EXCLUDED_VIDEO_IDS = frozenset(("Scuba_KD74Ywuy9ng", "Scuba_Um4kqB8bQBg"))
_PLACEHOLDER_IDS = frozenset((
    "day3-verification", "t07", "team_id", "team_alpha", "demo", "smoke",
    "your_registered_team_id", "your_team_id",
))
_OUTPUT_KEYS = frozenset(("team_id", "video_id", "duration_sec", "label", "actions", "highlights"))
_LABEL_KEYS = frozenset(("name", "score"))
_ACTION_KEYS = frozenset(("segment", "verb", "noun", "score"))
_HIGHLIGHT_KEYS = frozenset(("segment",))
_DURATION_TOLERANCE = Decimal("0.5")
_HIGHLIGHT_MINIMUM = Decimal("4")
_HIGHLIGHT_BUDGET = Decimal("0.15")
_MAX_ACTIONS = 2000


def validate_team_id(team_id: str) -> str:
    """Require the supplied registered identifier and reject known example IDs."""
    if not isinstance(team_id, str) or not team_id or team_id != team_id.strip():
        raise ValueError("a non-empty registered team ID without surrounding whitespace is required")
    if team_id.casefold() in _PLACEHOLDER_IDS:
        raise ValueError(f"{team_id!r} is a placeholder. Supply the exact registered team ID")
    return team_id


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    data: dict[str, object] = {}
    for key, value in pairs:
        if key in data:
            raise ValueError(f"duplicate JSON key {key!r}")
        data[key] = value
    return data


def _reject_nonfinite(token: str) -> None:
    raise ValueError(f"non-finite JSON number {token}")


def _read_prediction(path: Path) -> object:
    return json.loads(
        path.read_text(encoding="utf-8-sig"),
        object_pairs_hook=_unique_object,
        parse_float=Decimal,
        parse_int=Decimal,
        parse_constant=_reject_nonfinite,
    )


def _keys(value: object, required: frozenset[str], field: str, error: Callable[[str], None]) -> bool:
    if not isinstance(value, dict):
        error(f"{field} must be an object")
        return False
    missing, extra = required - value.keys(), value.keys() - required
    if missing or extra:
        error(f"{field} keys do not match the schema (missing {sorted(missing)}, unexpected {sorted(extra)})")
    return not (missing or extra)


def _number(value: object, field: str, error: Callable[[str], None]) -> Decimal | None:
    if isinstance(value, Decimal) and value.is_finite() and math.isfinite(value):
        return value
    error(f"{field} must be a finite JSON number")
    return None


def _score(value: object, field: str, error: Callable[[str], None]) -> None:
    score = _number(value, field, error)
    if score is not None and not 0 <= score <= 1:
        error(f"{field} must be in [0, 1]")


def _off_centisecond_grid(value: Decimal) -> bool:
    _, digits, exponent = value.as_tuple()
    extra = -2 - exponent
    return extra > 0 and any(digits[-extra:])


def _interval(value: object, field: str, duration: Decimal | None,
              error: Callable[[str], None]) -> tuple[Decimal, Decimal] | None:
    if not isinstance(value, list) or len(value) != 2:
        error(f"{field} must be an array with exactly [start, end]")
        return None
    start = _number(value[0], f"{field}[0]", error)
    end = _number(value[1], f"{field}[1]", error)
    if start is None or end is None:
        return None
    if _off_centisecond_grid(start) or _off_centisecond_grid(end):
        error(f"{field} timestamps must have at most two decimal places")
        return None
    if start < 0 or end <= start or (duration is not None and end > duration + _DURATION_TOLERANCE):
        error(f"{field} requires 0 <= start < end <= duration_sec + 0.5")
        return None
    return start, end


def _check_label(value: object, dataset: str, taxonomy: Taxonomy, error: Callable[[str], None]) -> None:
    if not _keys(value, _LABEL_KEYS, "label", error):
        return
    name = value["name"]
    if not taxonomy.has_label(name):
        error(f"label.name is not an exact taxonomy label: {name!r}")
    elif dataset == "epic_kitchens_100" and name != "cooking":
        error("label.name must be 'cooking' for EPIC-KITCHENS-100")
    elif dataset == "fpvsum" and name == "cooking":
        error("label.name must be an FPVSum category or 'other'")
    _score(value["score"], "label.score", error)


def _check_actions(value: object, duration: Decimal | None, taxonomy: Taxonomy,
                   error: Callable[[str], None]) -> None:
    if not isinstance(value, list):
        error("actions must be an array")
        return
    if len(value) > _MAX_ACTIONS:
        error(f"actions must contain at most {_MAX_ACTIONS} items")
        return
    for index, action in enumerate(value):
        field = f"actions[{index}]"
        if not _keys(action, _ACTION_KEYS, field, error):
            continue
        if not taxonomy.has_verb(action["verb"]):
            error(f"{field}.verb is not an exact taxonomy verb: {action['verb']!r}")
        if not taxonomy.has_noun(action["noun"]):
            error(f"{field}.noun is not an exact taxonomy noun: {action['noun']!r}")
        _interval(action["segment"], f"{field}.segment", duration, error)
        _score(action["score"], f"{field}.score", error)


def _check_highlights(value: object, duration: Decimal | None, reference_duration: Decimal,
                      error: Callable[[str], None], warning: Callable[[str], None]) -> None:
    if not isinstance(value, list) or not value:
        error("highlights must be a non-empty array")
        return
    intervals: list[tuple[Decimal, Decimal]] = []
    for index, highlight in enumerate(value):
        field = f"highlights[{index}]"
        if not _keys(highlight, _HIGHLIGHT_KEYS, field, error):
            continue
        interval = _interval(highlight["segment"], f"{field}.segment", duration, error)
        if interval is None:
            continue
        start, end = interval
        if intervals and start < intervals[-1][0]:
            error(f"{field}.segment is not in chronological order")
        elif intervals and start < intervals[-1][1]:
            error(f"{field}.segment overlaps the previous highlight")
        if end - start < _HIGHLIGHT_MINIMUM:
            warning(f"{field}.segment is shorter than 4 seconds")
        intervals.append(interval)
    if not any(end - start >= _HIGHLIGHT_MINIMUM for start, end in intervals):
        error("at least one highlight must be 4 seconds or longer")
    total = sum((end - start for start, end in intervals), Decimal(0))
    budget = reference_duration * _HIGHLIGHT_BUDGET
    if total > budget:
        warning(f"highlight duration {total:.2f}s exceeds the 15% target ({budget:.2f}s)")


def _check_prediction(data: object, entry: ManifestEntry, team_id: str, taxonomy: Taxonomy,
                      error: Callable[[str], None], warning: Callable[[str], None]) -> None:
    if not _keys(data, _OUTPUT_KEYS, "prediction", error):
        return
    if data["team_id"] != team_id:
        error(f"team_id must match the registered ID {team_id!r}")
    if data["video_id"] != entry.video_id:
        error(f"video_id must match manifest ID and filename {entry.video_id!r}")
    reference_duration = Decimal(str(entry.duration_sec))
    duration = _number(data["duration_sec"], "duration_sec", error)
    if duration is not None and duration <= 0:
        error("duration_sec must be positive")
        duration = None
    if duration is not None and abs(duration - reference_duration) > _DURATION_TOLERANCE:
        error(f"duration_sec must be within 0.5 seconds of manifest duration {reference_duration}s")
    _check_label(data["label"], entry.dataset, taxonomy, error)
    _check_actions(data["actions"], duration, taxonomy, error)
    _check_highlights(data["highlights"], duration, reference_duration, error, warning)


def validate_directory(output_dir: Path, manifest: tuple[ManifestEntry, ...], taxonomy: Taxonomy,
                       team_id: str, *, allow_missing: bool = False,
                       excluded_video_ids: frozenset[str] = EXCLUDED_VIDEO_IDS) -> dict:
    """Inspect every candidate JSON. Partial mode permits missing IDs only."""
    validate_team_id(team_id)
    if not output_dir.is_dir():
        raise ValueError(f"output directory does not exist: {output_dir}")
    eligible = {entry.video_id: entry for entry in manifest if entry.video_id not in excluded_video_ids}
    excluded_folded = {video_id.casefold() for video_id in excluded_video_ids}
    candidates = sorted(path for path in output_dir.rglob("*") if path.suffix.casefold() == ".json")
    seen_filenames: dict[str, list[str]] = defaultdict(list)
    seen_ids: dict[str, list[str]] = defaultdict(list)
    excluded_files: set[str] = set()
    unexpected_files: set[str] = set()
    present: set[str] = set()
    valid_files: set[str] = set()
    errors: list[str] = []
    warnings: list[str] = []

    for path in candidates:
        relative = path.relative_to(output_dir).as_posix()
        first_error = len(errors)

        def error(message: str) -> None:
            errors.append(f"{relative}: {message}")

        def warning(message: str) -> None:
            warnings.append(f"{relative}: {message}")

        seen_filenames[path.name.casefold()].append(relative)
        is_flat = path.parent == output_dir and path.suffix == ".json"
        if path.stem.casefold() in excluded_folded:
            excluded_files.add(relative)
            error("output is for an explicitly excluded FPVSum video")
        elif path.stem not in eligible or not is_flat:
            unexpected_files.add(relative)
            error("unexpected output filename. Expected <video_id>.json directly in the output directory")
        else:
            present.add(path.stem)
        if path.is_symlink() or not path.is_file():
            error("output must be a regular file")
            continue
        try:
            data = _read_prediction(path)
        except (OSError, ValueError, InvalidOperation, RecursionError) as exc:
            error(f"invalid JSON: {exc}")
            continue
        if isinstance(data, dict) and isinstance(video_id := data.get("video_id"), str):
            seen_ids[video_id.casefold()].append(relative)
            if video_id.casefold() in excluded_folded and relative not in excluded_files:
                excluded_files.add(relative)
                error("video_id belongs to an explicitly excluded FPVSum video")
        if is_flat and path.stem in eligible:
            _check_prediction(data, eligible[path.stem], team_id, taxonomy, error, warning)
            if len(errors) == first_error:
                valid_files.add(relative)

    duplicates = {
        "filenames": [group for group in seen_filenames.values() if len(group) > 1],
        "video_ids": [group for group in seen_ids.values() if len(group) > 1],
    }
    for kind, groups in duplicates.items():
        for group in groups:
            errors.append(f"duplicate {kind}: {', '.join(group)}")
            valid_files.difference_update(group)
    missing_ids = sorted(eligible.keys() - present)
    if missing_ids and not allow_missing:
        errors.append(f"missing {len(missing_ids)} eligible output file(s)")
    if allow_missing and not valid_files and not errors:
        errors.append("no eligible outputs were validated")

    return {
        "validator": "AURA local six-key submission validator",
        "official_validator": False,
        "team_id": team_id,
        "mode": "allow_missing" if allow_missing else "strict",
        "manifest_count": len(manifest),
        "eligible_count": len(eligible),
        "present_count": len(present),
        "valid_count": len(valid_files),
        "files_found": len(candidates),
        "excluded_ids": sorted(excluded_video_ids),
        "excluded_from_manifest": sorted(entry.video_id for entry in manifest if entry.video_id in excluded_video_ids),
        "excluded_files": sorted(excluded_files),
        "missing_ids": missing_ids,
        "unexpected_files": sorted(unexpected_files),
        "duplicates": duplicates,
        "warnings": warnings,
        "errors": errors,
        "passed": not errors,
    }


def _write_report(path: Path, result: dict, output_dir: Path, manifest: Path, taxonomy: Path) -> None:
    resolved = path.resolve()
    if resolved.is_relative_to(output_dir.resolve()) or resolved in (manifest.resolve(), taxonomy.resolve()):
        raise ValueError("the report must be outside predictions and separate from manifest and taxonomy")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
        stream.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path, help="Directory containing outputs/<video_id>.json files")
    parser.add_argument("--team-id", required=True, help="Exact registered team identifier")
    parser.add_argument("--manifest", type=Path, default=BUNDLED_MANIFEST_PATH)
    parser.add_argument("--taxonomy", type=Path, default=bundled_taxonomy_path())
    parser.add_argument("--allow-missing", action="store_true", help="Check existing outputs while reporting missing IDs")
    parser.add_argument("--full-manifest", action="store_true", help="validate every ID including both Scuba entries")
    parser.add_argument("--report", type=Path, help="New JSON report outside the output directory")
    args = parser.parse_args(argv)
    try:
        team_id = validate_team_id(args.team_id)
        result = validate_directory(
            args.output_dir, load_manifest(args.manifest), load_taxonomy(args.taxonomy),
            team_id, allow_missing=args.allow_missing,
            excluded_video_ids=frozenset() if args.full_manifest else EXCLUDED_VIDEO_IDS,
        )
        if args.report is not None:
            _write_report(args.report, result, args.output_dir, args.manifest, args.taxonomy)
    except (OSError, ValueError) as exc:
        print(f"Validation could not run: {exc}", file=sys.stderr)
        return 2

    for warning in result["warnings"]:
        print(f"WARNING: {warning}")
    for error in result["errors"]:
        print(f"ERROR: {error}", file=sys.stderr)
    print(
        f"AURA local validation ({result['mode']}): {result['valid_count']}/{result['eligible_count']} eligible outputs valid, "
        f"{len(result['missing_ids'])} missing, {len(result['excluded_from_manifest'])} excluded, "
        f"{len(result['warnings'])} warning(s), {len(result['errors'])} error(s)."
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
