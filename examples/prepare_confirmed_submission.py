"""Run the frozen batch only after the registered submission scope is confirmed."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from hashlib import file_digest, sha256
import json
from pathlib import Path, PureWindowsPath
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


QA_ID = "internal-qa-20261121"
HIGHLIGHT_POLICY = {"minimum_seconds": 4, "minimum_applies_to": "at_least_one_segment",
                    "budget_ratio": 0.15, "budget_is_soft": True, "short_video_policy": "minimum"}


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return file_digest(source, "sha256").hexdigest()


def read_approval(path: Path) -> dict:
    def unique_fields(pairs):
        fields = {}
        for name, value in pairs:
            if name in fields:
                raise ValueError(f"Duplicate approval field: {name}")
            fields[name] = value
        return fields

    approval = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=unique_fields)
    if not isinstance(approval, dict):
        raise ValueError("The approval record must be a JSON object")
    return approval


def approved_entries(approval: dict, manifest: Path, team_id: str,
                     official_validator: Path) -> tuple[tuple[ManifestEntry, ...], frozenset[str]]:
    validate_team_id(team_id)
    if (team_id.endswith(".") or PureWindowsPath(team_id).is_reserved()
            or any(char in '<>:"/\\|?*' or ord(char) < 32 for char in team_id)):
        raise ValueError("The registered team ID must also be a portable archive folder name")
    if team_id.casefold() == QA_ID or approval.get("team_id") != team_id:
        raise ValueError("The exact registered team ID must match the confirmation and cannot be the QA ID")
    reference = approval.get("confirmation_reference")
    if not isinstance(reference, str) or not reference.strip():
        raise ValueError("A reference to written organizer confirmation is required")
    if approval.get("validation_profile") != "readme6":
        raise ValueError("The authoritatively confirmed validation profile must match the frozen readme6 pipeline")
    policy = approval.get("highlight_policy")
    if not isinstance(policy, dict) or policy != HIGHLIGHT_POLICY or policy.get("budget_is_soft") is not True:
        raise ValueError("The confirmed highlight policy must match the frozen four-second minimum-first and soft 15% target")
    exclusions = approval.get("excluded_video_ids")
    if exclusions == []:
        excluded = frozenset()
    elif isinstance(exclusions, list) and sorted(EXCLUDED_VIDEO_IDS) == sorted(str(item) for item in exclusions):
        excluded = EXCLUDED_VIDEO_IDS
    else:
        raise ValueError("Confirm the full scope or both named Scuba exclusions")
    if not isinstance(approval.get("manifest_sha256"), str) or digest(manifest) != approval["manifest_sha256"]:
        raise ValueError("The supplied manifest does not match the approved SHA-256")
    if (not isinstance(approval.get("official_validator_sha256"), str)
            or digest(official_validator) != approval["official_validator_sha256"]):
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
        reader = csv.DictReader(source, strict=True)
        if reader.fieldnames != ["video_id", "sha256", "source_reference"]:
            raise ValueError("Media provenance needs columns video_id,sha256,source_reference")
        for row in reader:
            video_id, expected, reference = (row[key] for key in reader.fieldnames)
            if (None in row or video_id in sources or not expected or not re.fullmatch(r"[0-9a-f]{64}", expected)
                    or not reference or not reference.strip()):
                raise ValueError(f"Invalid or duplicate media provenance at CSV line {reader.line_num} for {video_id!r}")
            sources[video_id] = (expected, reference)
    expected_ids = {entry.video_id for entry in entries}
    if sources.keys() != expected_ids:
        missing = sorted(expected_ids - sources.keys())
        unexpected = sorted(sources.keys() - expected_ids)
        raise ValueError(f"Provenance scope mismatch. Missing={missing}, unexpected={unexpected}")
    candidates = index_media(media_dirs)
    casefolded = {}
    for stem in candidates:
        casefolded.setdefault(stem.casefold(), []).append(stem)
    receipt = []
    for entry in entries:
        paths = candidates.get(entry.video_id, [])
        expected, source_reference = sources[entry.video_id]
        row = {"video_id": entry.video_id, "source_reference": source_reference, "expected_sha256": expected}
        if not paths:
            aliases = casefolded.get(entry.video_id.casefold(), [])
            row.update(status="wrong_case_original" if aliases else "missing_original",
                       candidates=[str(path) for stem in aliases for path in candidates[stem]])
        elif len(paths) != 1 or casefolded[entry.video_id.casefold()] != [entry.video_id]:
            row.update(status="ambiguous_original", candidates=[str(path) for stem in casefolded[entry.video_id.casefold()]
                                                                for path in candidates[stem]])
        elif paths[0].is_symlink() or not paths[0].is_file():
            row.update(status="linked_or_non_file", candidates=[str(paths[0])])
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
    run = args.run_dir.resolve()
    if run.is_relative_to(ROOT / "TEAM_ID"):
        raise ValueError("Use a fresh run directory outside the production team tree")
    run.mkdir(parents=True, exist_ok=False)
    preflight_only = getattr(args, "preflight_only", False)
    coverage = {"expected": None, "official_validator_run": False, "submission_ready": False,
                "inference_started": False, "locally_validated": 0, "outputs": []}
    report_path = run / "coverage.json"
    stage = "approval"
    try:
        approval = read_approval(args.approval)
        manifest_bytes = args.manifest.read_bytes()
        entries, excluded = approved_entries(approval, args.manifest, args.team_id, args.official_validator)
        if sha256(manifest_bytes).hexdigest() != approval["manifest_sha256"] or args.manifest.read_bytes() != manifest_bytes:
            raise ValueError("The authorized manifest changed while preparing the run")
        coverage["expected"] = len(entries)
        stage = "model_assets"
        invalid = [name for name, (_, expected) in WEIGHT_ASSETS.items()
                   if not has_expected_sha256(args.weights / name, expected)]
        if invalid:
            raise ValueError("Missing or corrupt frozen CLIP assets: " + ", ".join(invalid))
    except (OSError, UnicodeError, ValueError) as error:
        coverage.update(status=f"blocked_{stage}", error=str(error))
        write_output_json(report_path, coverage)
        return False
    (run / "authorized-manifest.csv").write_bytes(manifest_bytes)
    selected = run / "selected-manifest.csv"
    with selected.open("x", encoding="utf-8", newline="") as destination:
        writer = csv.writer(destination)
        writer.writerow(("video_id", "duration_sec", "dataset"))
        writer.writerows((entry.video_id, entry.duration_sec, entry.dataset) for entry in entries)

    try:
        directories = list(dict.fromkeys(path.resolve() for path in args.media_dir))
        inputs = media_receipt(entries, directories, args.provenance)
    except (OSError, ValueError, UnicodeError, csv.Error) as error:
        coverage.update(status="blocked_input_provenance", error=str(error))
        write_output_json(report_path, coverage)
        return False
    write_output_json(run / "input-provenance.json", {
        "confirmation_reference": approval["confirmation_reference"],
        "official_validator_sha256": approval["official_validator_sha256"],
        "excluded_video_ids": sorted(excluded),
        "selected_manifest_sha256": digest(selected), "media": inputs,
    })
    counts = Counter(row["status"] for row in inputs)
    checked = counts["verified"]
    coverage["input_files_verified"] = checked
    coverage["inputs_by_status"] = dict(sorted(counts.items()))
    coverage["blocked_input_ids"] = [row["video_id"] for row in inputs if row["status"] != "verified"]
    if checked != len(entries):
        coverage["status"] = "blocked_input_provenance"
        write_output_json(report_path, coverage)
        return False

    if preflight_only:
        coverage["status"] = "preflight_passed"
        write_output_json(report_path, coverage)
        return True

    coverage.update(status="running", inference_started=True)
    write_output_json(report_path, coverage)
    inference = run / "inference"
    try:
        report = run_manifest(selected, directories, inference, args.team_id, args.weights)
        output_dir = inference / "predictions"
        validation = validate_directory(output_dir, entries, load_bundled_taxonomy(), args.team_id,
                                        excluded_video_ids=excluded)
        write_output_json(run / "local-validation.json", validation)
    except (OSError, ValueError, RuntimeError) as error:
        coverage.update(status="inference_interrupted", error=str(error))
        write_output_json(report_path, coverage)
        raise

    rows = report["videos"]
    reported_paths = {row["video_id"]: row.get("source") for row in rows if row.get("status") == "succeeded"}
    expected_ids = {entry.video_id for entry in entries}
    run_scope_ok = len(rows) == len(entries) and reported_paths.keys() == expected_ids
    changes = []
    for row in inputs:
        path = Path(row["path"])
        try:
            confirmed = (reported_paths.get(row["video_id"]) == str(path) and not path.is_symlink()
                         and digest(path) == row["expected_sha256"])
        except OSError:
            confirmed = False
        if not confirmed:
            changes.append(row["video_id"])
    files = sorted(p for p in output_dir.glob("*.json") if p.is_file() and not p.is_symlink())
    complete = (validation["passed"] and validation["valid_count"] == len(entries) and not changes and run_scope_ok
                and report["totals"]["succeeded"] == len(entries)
                and {path.name for path in files} == {f"{video_id}.json" for video_id in expected_ids})
    coverage.update(status="locally_complete" if complete else "incomplete",
                    locally_validated=validation["valid_count"],
                    missing_prediction_ids=validation["missing_ids"], unverified_run_sources=changes,
                    run_scope_matches_approval=run_scope_ok,
                    outputs=[{"path": p.relative_to(run).as_posix(), "sha256": digest(p)} for p in files])
    write_output_json(report_path, coverage)
    return complete


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("approval", "manifest", "provenance", "official-validator", "weights", "run-dir"):
        parser.add_argument(f"--{name}", required=True, type=Path)
    parser.add_argument("--media-dir", action="append", required=True, type=Path)
    parser.add_argument("--team-id", required=True, help="exact case-sensitive registered identifier")
    parser.add_argument("--preflight-only", action="store_true", help="verify inputs and write receipts without inference")
    args = parser.parse_args()
    if sys.platform != "linux" and not args.preflight_only:
        parser.error("Inference requires Linux or WSL. Use --preflight-only to check inputs on this platform.")
    try:
        complete = prepare(args)
    except (OSError, ValueError, RuntimeError, csv.Error) as error:
        parser.exit(2, f"Run stopped: {error}\n")
    outcome = "Preflight passed. Inference and official validation are pending" if args.preflight_only else "Locally complete. Official validation is pending"
    if not complete:
        outcome = "Blocked or incomplete. Inference or submission cannot be treated as complete"
    print(f"{outcome}. See {args.run_dir / 'coverage.json'}")
    return 0 if complete else 1


if __name__ == "__main__":
    sys.exit(main())
