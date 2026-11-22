"""Load the organizer's manifest as an ordered set of portable video IDs."""
from __future__ import annotations

import csv
import math
import re
from dataclasses import dataclass
from pathlib import Path

BUNDLED_MANIFEST_PATH = Path(__file__).resolve().parent.parent / "resources" / "manifest.csv"
_COLUMNS = ["video_id", "duration_sec", "dataset"]
_DATASETS = frozenset(("epic_kitchens_100", "fpvsum"))
_VIDEO_ID = re.compile(r"[A-Za-z0-9_-]+")
_RESERVED_IDS = frozenset(("con", "prn", "aux", "nul")) | {
    f"{prefix}{number}" for prefix in ("com", "lpt") for number in range(1, 10)
}


class ManifestError(ValueError):
    """A manifest is unreadable or does not match the student-kit format."""


@dataclass(frozen=True)
class ManifestEntry:
    video_id: str
    dataset: str
    duration_sec: float


def load_manifest(path: Path = BUNDLED_MANIFEST_PATH) -> tuple[ManifestEntry, ...]:
    """Load all rows in file order, including from a compatible custom subset."""
    entries: list[ManifestEntry] = []
    seen_ids: set[str] = set()
    try:
        with Path(path).open(encoding="utf-8-sig", newline="") as stream:
            rows = csv.reader(stream, strict=True)
            if next(rows, None) != _COLUMNS:
                raise ManifestError(f"{path}: expected header {','.join(_COLUMNS)}")
            for row in rows:
                location = f"{path}:{rows.line_num}"
                if len(row) != len(_COLUMNS):
                    raise ManifestError(f"{location}: expected exactly three CSV fields")
                video_id, raw_duration, dataset = row
                canonical_id = video_id.casefold()
                if not _VIDEO_ID.fullmatch(video_id) or canonical_id in _RESERVED_IDS:
                    raise ManifestError(f"{location}: unsafe video_id {video_id!r}")
                if canonical_id in seen_ids:
                    raise ManifestError(f"{location}: duplicate video_id {video_id!r}")
                try:
                    duration = float(raw_duration)
                except ValueError as exc:
                    raise ManifestError(f"{location}: invalid duration_sec {raw_duration!r}") from exc
                if not math.isfinite(duration) or duration <= 0:
                    raise ManifestError(f"{location}: duration_sec must be finite and positive")
                if dataset not in _DATASETS:
                    raise ManifestError(f"{location}: unknown dataset {dataset!r}")
                entries.append(ManifestEntry(video_id, dataset, duration))
                seen_ids.add(canonical_id)
    except (OSError, UnicodeError, csv.Error) as exc:
        raise ManifestError(f"cannot read manifest {path}: {exc}") from exc
    if not entries:
        raise ManifestError(f"{path}: no video entries")
    return tuple(entries)
