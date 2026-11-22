"""Run the stock AURA launcher on every row of a Track 4 manifest."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CODE = ROOT / "TEAM_ID" / "code"
sys.path[:0] = [str(CODE), str(ROOT)]

from aura import config
from aura.clip_backend import MODEL_REPOSITORY, MODEL_REVISION, WEIGHT_ASSETS
from aura.clip_predictor import ClipPredictionSettings
from aura.io_utils import write_output_json
from aura.manifest import BUNDLED_MANIFEST_PATH, ManifestEntry, load_manifest
from aura.preprocessing import get_video_info
from aura.profile_readme6 import Readme6Profile
from aura.taxonomy import Taxonomy, load_bundled_taxonomy
from evaluation.tsm.measure_command import measure


PROFILE = "readme6"
SETTINGS = ClipPredictionSettings()
DURATION_TOLERANCE_SECONDS = 0.5
REPORT_NAME = "processing-report.json"


def launcher_environment(team_id: str, weights: Path) -> dict[str, str]:
    """Override every setting read by the single-video launcher."""
    return {
        "PYTHON": sys.executable,
        "AURA_PROFILE": PROFILE,
        "AURA_TEAM_ID": team_id,
        "AURA_WEIGHTS_DIR": str(weights),
        "AURA_ACTION_WINDOW_SECONDS": str(SETTINGS.action_window_s),
        "AURA_SAMPLE_FPS": str(config.SAMPLE_FPS),
        "AURA_BUDGET_RATIO": str(config.HIGHLIGHT_BUDGET_RATIO),
        "AURA_MIN_HIGHLIGHT_SECONDS": str(config.MIN_HIGHLIGHT_SEGMENT_S),
        "AURA_HIGHLIGHT_POLICY": config.SHORT_HIGHLIGHT_POLICY,
    }


def index_media(directories: list[Path]) -> dict[str, list[Path]]:
    """Use exact stems and case-insensitive MP4 extensions in flat directories."""
    found: dict[str, list[Path]] = defaultdict(list)
    for directory in directories:
        if not directory.is_dir():
            raise ValueError(f"media directory does not exist or is not a directory: {directory}")
        for path in sorted(directory.iterdir()):
            if path.suffix.lower() == ".mp4":
                found[path.stem].append(path)
    return found


def process_entry(entry: ManifestEntry, candidates: list[Path], run_dir: Path,
                  settings: dict[str, str], taxonomy: Taxonomy, row: dict) -> None:
    """Record an individual outcome and publish only a checked prediction."""
    if not candidates:
        row.update(status="missing_input", error="no <video_id>.mp4 in the media directories")
        return
    if len(candidates) != 1:
        row.update(status="ambiguous_input", error="multiple candidate MP4 paths",
                   candidates=[str(path) for path in candidates])
        return

    source = candidates[0]
    row["source"] = str(source)
    try:
        info = get_video_info(source)
    except (OSError, ValueError) as exc:
        row.update(status="invalid_input", error=str(exc))
        return
    row["source_duration_sec"] = info["duration"]
    if abs(info["duration"] - entry.duration_sec) > DURATION_TOLERANCE_SECONDS + config.TIME_EPSILON:
        row.update(status="duration_mismatch", error="source differs from the manifest by more than 0.5 seconds")
        return

    log_path = run_dir / "logs" / f"{entry.video_id}.log"
    row["log"] = log_path.relative_to(run_dir).as_posix()
    with tempfile.TemporaryDirectory(prefix=".prediction-", dir=run_dir) as staging:
        staged = Path(staging) / f"{entry.video_id}.json"
        command = ["env", *(f"{key}={value}" for key, value in settings.items()),
                   str(ROOT / "TEAM_ID" / "run.sh"), str(source), str(staged)]
        try:
            measurement = measure(command, log_path)
        except (OSError, RuntimeError) as exc:
            row.update(status="launcher_error", error=str(exc))
            return
        row.update(measurement)
        if measurement["exit_code"] != 0:
            row.update(status="launcher_failed", error=f"launcher exit code {measurement['exit_code']}")
            return

        try:
            data = json.loads(staged.read_text(encoding="utf-8"))
            validation = Readme6Profile().validate(
                data, reference_duration_sec=entry.duration_sec, taxonomy=taxonomy,
                allow_short_highlights=info["duration"] < config.README6_MIN_HIGHLIGHT_SEGMENT_S,
            )
            row["validation_warnings"] = [issue.format() for issue in validation.warnings]
            errors = [issue.format() for issue in validation.errors]
            if isinstance(data, dict):
                if data.get("video_id") != entry.video_id:
                    errors.append("output video_id differs from the manifest ID")
                if data.get("team_id") != settings["AURA_TEAM_ID"]:
                    errors.append("output team_id differs from the requested team ID")
            if errors:
                row.update(status="invalid_output", error="; ".join(errors), validation_errors=errors)
                return
        except (OSError, ValueError) as exc:
            row.update(status="invalid_output", error=str(exc))
            return

        destination = run_dir / "predictions" / staged.name
        try:
            os.replace(staged, destination)
        except OSError as exc:
            row.update(status="publish_error", error=str(exc))
            return
        row.update(status="succeeded", output=destination.relative_to(run_dir).as_posix())


def write_report(path: Path, report: dict) -> None:
    totals = Counter(row["status"] for row in report["videos"])
    report["totals"] = {
        "expected": len(report["videos"]),
        "succeeded": totals["succeeded"],
        "by_status": dict(sorted(totals.items())),
    }
    write_output_json(path, report)


def run_manifest(manifest: Path, directories: list[Path], run_dir: Path, team_id: str,
                 weights: Path) -> dict:
    """Process in manifest order and checkpoint the report after every row."""
    if sys.platform != "linux":
        raise ValueError("the manifest runner requires Linux for per-video peak RSS accounting")
    if not team_id.strip():
        raise ValueError("team ID must be non-empty")
    manifest, run_dir, weights = (path.expanduser().resolve() for path in (manifest, run_dir, weights))
    directories = list(dict.fromkeys(path.expanduser().resolve() for path in directories))
    entries = load_manifest(manifest)
    candidates = index_media(directories)
    taxonomy = load_bundled_taxonomy()
    settings = launcher_environment(team_id, weights)
    rows = [
        {
            "video_id": entry.video_id,
            "dataset": entry.dataset,
            "manifest_duration_sec": entry.duration_sec,
            "status": "pending",
            "wall_seconds": None,
            "peak_rss_kib": None,
            "exit_code": None,
        }
        for entry in entries
    ]
    report = {
        "manifest_path": str(manifest),
        "manifest_sha256": sha256(manifest.read_bytes()).hexdigest(),
        "media_directories": [str(directory) for directory in directories],
        "model": {
            "backend": "CLIP ViT-B/32, ONNX Runtime CPUExecutionProvider",
            "repository": MODEL_REPOSITORY,
            "revision": MODEL_REVISION,
            "expected_weight_sha256": {filename: digest for filename, (_, digest) in WEIGHT_ASSETS.items()},
            "clip_prediction_settings": asdict(SETTINGS),
            "launcher_environment": settings,
        },
        "validation": {
            "profile": PROFILE,
            "official_validator_run": False,
            "duration_tolerance_sec": DURATION_TOLERANCE_SECONDS,
        },
        "videos": rows,
    }
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "predictions").mkdir()
    report_path = run_dir / REPORT_NAME
    write_report(report_path, report)
    for entry, row in zip(entries, rows, strict=True):
        process_entry(entry, candidates.get(entry.video_id, []), run_dir, settings, taxonomy, row)
        write_report(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=BUNDLED_MANIFEST_PATH)
    parser.add_argument("--media-dir", type=Path, action="append", required=True,
                        help="directory containing MP4s named by video ID; repeat for multiple directories")
    parser.add_argument("--run-dir", type=Path, required=True, help="write a new run directory")
    parser.add_argument("--team-id", required=True)
    parser.add_argument("--weights", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run_manifest(args.manifest, args.media_dir, args.run_dir, args.team_id, args.weights)
    except (OSError, ValueError) as exc:
        parser.exit(2, f"manifest run failed: {exc}\n")
    totals = report["totals"]
    print(f"{totals['succeeded']}/{totals['expected']} locally validated predictions; "
          f"report: {args.run_dir.expanduser() / REPORT_NAME}")
    return 0 if totals["succeeded"] == totals["expected"] else 1


if __name__ == "__main__":
    sys.exit(main())
