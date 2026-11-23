"""Run the frozen batch only after the registered submission scope is confirmed."""
from __future__ import annotations

import argparse
import csv
from hashlib import file_digest, sha256
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "TEAM_ID/code"), str(ROOT)]

from aura.clip_backend import WEIGHT_ASSETS, has_expected_sha256
from aura.io_utils import write_output_json
from aura.manifest import ManifestEntry, load_manifest
from aura.taxonomy import load_bundled_taxonomy
from examples.run_manifest import index_media, run_manifest
from validate_outputs import EXCLUDED_VIDEO_IDS, validate_directory, validate_team_id


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return file_digest(source, "sha256").hexdigest()


def approved_entries(approval: dict, manifest: Path, team_id: str,
                     official_validator: Path) -> tuple[tuple[ManifestEntry, ...], frozenset[str]]:
    validate_team_id(team_id)
    if team_id.casefold() == "internal-qa-20261121" or approval.get("team_id") != team_id:
        raise ValueError("The exact registered team ID must match the confirmation and cannot be the QA ID")
    reference = approval.get("confirmation_reference")
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("A reference to written organizer confirmation is required")
    if approval.get("validation_profile") != "readme6":
        raise ValueError("The authoritatively confirmed validation profile must match the frozen readme6 pipeline")
    exclusions = approval.get("excluded_video_ids")
    if exclusions == []:
        excluded = frozenset()
    elif isinstance(exclusions, list) and sorted(EXCLUDED_VIDEO_IDS) == sorted(str(item) for item in exclusions):
        excluded = EXCLUDED_VIDEO_IDS
    else:
        raise ValueError("Confirm the full scope or both named Scuba exclusions")
    if digest(manifest) != approval.get("manifest_sha256"):
        raise ValueError("The supplied manifest does not match the approved SHA-256")
    if digest(official_validator) != approval.get("official_validator_sha256"):
        raise ValueError("The official validator file does not match the recorded SHA-256")
    kit = {entry.video_id: entry for entry in load_manifest()}
    approved = load_manifest(manifest)
    selected = tuple(entry for entry in approved if entry.video_id not in excluded)
    expected = {key: value for key, value in kit.items() if key not in excluded}
    if {entry.video_id: entry for entry in selected} != expected or any(kit.get(row.video_id) != row for row in approved):
        raise ValueError("The manifest rows do not match the confirmed 187- or 185-video kit scope")
    return selected, excluded


def media_receipt(entries: tuple[ManifestEntry, ...], media_dirs: list[Path],
                  provenance: Path) -> list[dict]:
    sources = {}
    with provenance.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        if reader.fieldnames != ["video_id", "sha256", "source_reference"]:
            raise ValueError("Media provenance needs columns video_id,sha256,source_reference")
        for row in reader:
            video_id, expected, reference = (row[key] for key in reader.fieldnames)
            if (None in row or video_id in sources or not expected or not re.fullmatch(r"[0-9a-f]{64}", expected)
                    or not reference or not reference.strip()):
                raise ValueError(f"Invalid or duplicate media provenance for {video_id!r}")
            sources[video_id] = (expected, reference)
    expected_ids = {entry.video_id for entry in entries}
    if sources.keys() != expected_ids:
        missing = sorted(expected_ids - sources.keys())
        unexpected = sorted(sources.keys() - expected_ids)
        raise ValueError(f"Provenance scope mismatch. Missing={missing}, unexpected={unexpected}")
    candidates = index_media(list(dict.fromkeys(path.resolve() for path in media_dirs)))
    receipt = []
    for entry in entries:
        paths = candidates.get(entry.video_id, [])
        expected, source_reference = sources[entry.video_id]
        row = {"video_id": entry.video_id, "source_reference": source_reference, "expected_sha256": expected}
        if len(paths) != 1 or paths[0].is_symlink() or not paths[0].is_file():
            row.update(status="missing_or_ambiguous_original", candidates=[str(path) for path in paths])
        else:
            path = paths[0]
            try:
                observed = digest(path)
                row.update(path=str(path), observed_sha256=observed,
                           status="verified" if observed == expected else "checksum_mismatch")
            except OSError as error:
                row.update(path=str(path), status="unreadable_original", error=str(error))
        receipt.append(row)
    return receipt


def prepare(args: argparse.Namespace) -> bool:
    manifest_bytes = args.manifest.read_bytes()
    approval = json.loads(args.approval.read_text(encoding="utf-8"))
    if not isinstance(approval, dict):
        raise ValueError("The approval record must be a JSON object")
    entries, excluded = approved_entries(approval, args.manifest, args.team_id, args.official_validator)
    if sha256(manifest_bytes).hexdigest() != approval["manifest_sha256"]:
        raise ValueError("The authorized manifest changed while preparing the run")
    invalid = [name for name, (_, expected) in WEIGHT_ASSETS.items()
               if not has_expected_sha256(args.weights / name, expected)]
    if invalid:
        raise ValueError("Missing or corrupt frozen CLIP assets: " + ", ".join(invalid))
    run = args.run_dir.resolve()
    if run.is_relative_to(ROOT / "TEAM_ID"):
        raise ValueError("Use a fresh run directory outside the production team tree")
    run.mkdir(parents=True, exist_ok=False)
    (run / "authorized-manifest.csv").write_bytes(manifest_bytes)
    selected = run / "selected-manifest.csv"
    with selected.open("x", encoding="utf-8", newline="") as destination:
        writer = csv.writer(destination)
        writer.writerow(("video_id", "duration_sec", "dataset"))
        writer.writerows((entry.video_id, entry.duration_sec, entry.dataset) for entry in entries)

    coverage = {"expected": len(entries), "official_validator_run": False, "outputs": []}
    try:
        inputs = media_receipt(entries, args.media_dir, args.provenance)
    except (OSError, ValueError, csv.Error) as error:
        coverage.update(status="blocked_input_provenance", locally_validated=0, error=str(error))
        write_output_json(run / "coverage.json", coverage)
        raise
    write_output_json(run / "input-provenance.json", {
        "approval": approval, "excluded_video_ids": sorted(excluded),
        "selected_manifest_sha256": digest(selected), "media": inputs,
    })
    checked = sum(row["status"] == "verified" for row in inputs)
    coverage["input_files_verified"] = checked
    if checked != len(entries):
        coverage.update(status="blocked_input_provenance", locally_validated=0)
        write_output_json(run / "coverage.json", coverage)
        return False

    coverage["status"] = "running"
    write_output_json(run / "coverage.json", coverage)
    inference = run / "inference"
    try:
        report = run_manifest(selected, args.media_dir, inference, args.team_id, args.weights)
    except (OSError, ValueError, RuntimeError) as error:
        coverage.update(status="inference_interrupted", error=str(error))
        write_output_json(run / "coverage.json", coverage)
        raise

    output_dir = inference / "predictions"
    validation = validate_directory(output_dir, entries, load_bundled_taxonomy(), args.team_id,
                                    excluded_video_ids=excluded)
    write_output_json(run / "local-validation.json", validation)
    reported_paths = {row["video_id"]: row.get("source") for row in report["videos"]}
    changes = []
    for row in inputs:
        path = Path(row["path"])
        try:
            confirmed = (reported_paths[row["video_id"]] == str(path) and not path.is_symlink()
                         and digest(path) == row["expected_sha256"])
        except OSError:
            confirmed = False
        if not confirmed:
            changes.append(row["video_id"])
    files = sorted(p for p in output_dir.glob("*.json") if p.is_file() and not p.is_symlink())
    complete = (validation["passed"] and not changes and report["totals"]["succeeded"] == len(entries))
    coverage.update(status="locally_complete" if complete else "incomplete",
                    locally_validated=validation["valid_count"],
                    missing_prediction_ids=validation["missing_ids"], unverified_run_sources=changes,
                    outputs=[{"path": p.relative_to(run).as_posix(), "sha256": digest(p)} for p in files])
    write_output_json(run / "coverage.json", coverage)
    return complete


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("approval", "manifest", "provenance", "official-validator", "weights", "run-dir"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--media-dir", action="append", required=True, type=Path)
    parser.add_argument("--team-id", required=True, help="exact case-sensitive registered identifier")
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("The batch runner requires Linux or WSL")
    try:
        complete = prepare(args)
    except (OSError, ValueError, RuntimeError, csv.Error) as error:
        parser.exit(2, f"Run stopped: {error}\n")
    print(f"{'Locally complete' if complete else 'Incomplete'}. See {args.run_dir / 'coverage.json'}")
    return 0 if complete else 1


if __name__ == "__main__":
    sys.exit(main())
