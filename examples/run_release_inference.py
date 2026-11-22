"""Run the unchanged Day 3 launcher over the eligible final-submission manifest."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "TEAM_ID/code"), str(ROOT)]

from aura.clip_backend import WEIGHT_ASSETS, has_expected_sha256
from aura.manifest import load_manifest
from examples.run_manifest import run_manifest
from validate_outputs import EXCLUDED_VIDEO_IDS, validate_team_id


def write_eligible_manifest(destination: Path) -> None:
    entries = load_manifest()
    excluded = {entry.video_id for entry in entries
                if entry.dataset == "fpvsum" and entry.video_id in EXCLUDED_VIDEO_IDS}
    if excluded != set(EXCLUDED_VIDEO_IDS):
        raise ValueError("the bundled manifest must contain both designated FPVSum exclusions")
    with destination.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("video_id", "duration_sec", "dataset"))
        writer.writerows(
            (entry.video_id, entry.duration_sec, entry.dataset)
            for entry in entries if entry.video_id not in excluded
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--media-dir", type=Path, action="append", required=True, help="repeat for multiple directories")
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True, help="create a fresh release run directory")
    parser.add_argument("--team-id", required=True, help="exact registered team identifier")
    args = parser.parse_args()

    try:
        validate_team_id(args.team_id)
        weights = args.weights.expanduser().resolve()
        invalid = [name for name, (_, digest) in WEIGHT_ASSETS.items()
                   if not has_expected_sha256(weights / name, digest)]
        if invalid:
            raise ValueError("missing or corrupt CLIP assets: " + ", ".join(invalid))
        args.run_dir = args.run_dir.expanduser().resolve()
        args.run_dir.mkdir(parents=True, exist_ok=False)
        eligible = args.run_dir / "eligible-manifest.csv"
        write_eligible_manifest(eligible)
        report = run_manifest(eligible, args.media_dir, args.run_dir / "inference", args.team_id, weights)
    except (OSError, ValueError) as error:
        parser.exit(2, f"release run could not complete: {error}\n")

    totals = report["totals"]
    print(f"{totals['succeeded']}/{totals['expected']} locally validated predictions")
    print(f"Run report {args.run_dir / 'inference' / 'processing-report.json'}")
    return 0 if totals["succeeded"] == totals["expected"] else 1


if __name__ == "__main__":
    sys.exit(main())
