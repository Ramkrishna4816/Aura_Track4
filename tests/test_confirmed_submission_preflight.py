"""Synthetic fixtures for approval, provenance, and archive gates. No model inference."""

from argparse import Namespace
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from examples import prepare_confirmed_submission as preflight
from examples.build_release_submission import validate_coverage_receipt


VIDEO_ID = "Fixture_001"
TEAM = "FixtureTeam"


@pytest.fixture
def fixture_args(tmp_path, monkeypatch):
    media = tmp_path / "media"
    media.mkdir()
    original = media / f"{VIDEO_ID}.MP4"
    original.write_bytes(b"synthetic source fixture, never decoded")
    manifest = tmp_path / "authorized.csv"
    manifest.write_text(f"video_id,duration_sec,dataset\n{VIDEO_ID},30,epic_kitchens_100\n", encoding="utf-8")
    validator = tmp_path / "validator-fixture.py"
    validator.write_text("raise RuntimeError('must never execute the validator in preflight')\n", encoding="utf-8")
    approval = tmp_path / "approval.json"
    approval.write_text(json.dumps({
        "team_id": TEAM, "confirmation_reference": "synthetic approval fixture",
        "validation_profile": "readme6", "highlight_policy": preflight.HIGHLIGHT_POLICY,
        "excluded_video_ids": [], "manifest_sha256": preflight.digest(manifest),
        "official_validator_sha256": preflight.digest(validator),
    }), encoding="utf-8")
    provenance = tmp_path / "provenance.csv"
    provenance.write_text(f"video_id,sha256,source_reference\n{VIDEO_ID},{preflight.digest(original)},fixture\n",
                          encoding="utf-8")
    read_manifest = preflight.load_manifest
    monkeypatch.setattr(preflight, "load_manifest", lambda path=manifest: read_manifest(path))
    monkeypatch.setattr(preflight, "has_expected_sha256", lambda *args: True)
    return Namespace(approval=approval, manifest=manifest, official_validator=validator, provenance=provenance,
                     media_dir=[media], weights=tmp_path, team_id=TEAM, run_dir=tmp_path / "run", preflight_only=True)


def coverage(args):
    return json.loads((args.run_dir / "coverage.json").read_text(encoding="utf-8"))


def model_call_must_not_run(*args):
    pytest.fail("the synthetic preflight unexpectedly reached model inference")


def test_preflight_only_verifies_sources_without_inference(fixture_args, monkeypatch):
    args = fixture_args
    monkeypatch.setattr(preflight, "run_manifest", model_call_must_not_run)
    assert preflight.prepare(args)
    report = coverage(args)
    assert report["status"] == "preflight_passed"
    assert report["input_files_verified"] == report["expected"] == 1
    assert report["outputs"] == []
    assert not (report["inference_started"] or report["official_validator_run"] or report["submission_ready"])
    assert not (args.run_dir / "inference").exists()
    original_report = (args.run_dir / "coverage.json").read_bytes()
    with pytest.raises(FileExistsError):
        preflight.prepare(args)
    assert (args.run_dir / "coverage.json").read_bytes() == original_report


@pytest.mark.parametrize("change, message", [
    ({"team_id": "fixtureteam"}, "exact registered team ID"),
    ({"highlight_policy": {}}, "confirmed highlight policy"),
    ({"official_validator_sha256": "0" * 64}, "official validator file"),
    ({"excluded_video_ids": ["Scuba_KD74Ywuy9ng"]}, "both named Scuba exclusions"),
])
def test_unapproved_inputs_report_blockers(fixture_args, monkeypatch, change, message):
    args = fixture_args
    monkeypatch.setattr(preflight, "run_manifest", model_call_must_not_run)
    content = json.loads(args.approval.read_text(encoding="utf-8"))
    args.approval.write_text(json.dumps(content | change), encoding="utf-8")
    assert not preflight.prepare(args)
    report = coverage(args)
    assert report["status"] == "blocked_approval"
    assert message in report["error"]
    assert not report["inference_started"]


def test_missing_approval_and_duplicate_fields_report_exact_failure(fixture_args):
    args = fixture_args
    args.approval.unlink()
    assert not preflight.prepare(args)
    assert coverage(args)["status"] == "blocked_approval"
    args.run_dir = args.run_dir.with_name("duplicate-approval")
    args.approval.write_text('{"team_id":"FixtureTeam","team_id":"Other"}', encoding="utf-8")
    assert not preflight.prepare(args)
    assert "Duplicate approval field: team_id" in coverage(args)["error"]


@pytest.mark.parametrize("condition, diagnostic", [
    ("duplicate", "ambiguous_original"),
    ("wrong_case", "wrong_case_original"),
    ("changed", "checksum_mismatch"),
    ("missing", "missing_original"),
])
def test_media_blockers_are_specific(fixture_args, monkeypatch, condition, diagnostic):
    args = fixture_args
    original = args.media_dir[0] / f"{VIDEO_ID}.MP4"
    second = args.media_dir[0].with_name("second-media")
    second.mkdir()
    args.media_dir.append(second)
    if condition == "duplicate":
        (second / original.name).write_bytes(original.read_bytes())
    elif condition == "wrong_case":
        original.rename(second / original.name.lower())
    elif condition == "changed":
        original.write_bytes(b"different synthetic bytes")
    else:
        original.unlink()
    monkeypatch.setattr(preflight, "run_manifest", model_call_must_not_run)
    assert not preflight.prepare(args)
    report = coverage(args)
    assert report["status"] == "blocked_input_provenance"
    assert report["blocked_input_ids"] == [VIDEO_ID]
    assert report["inputs_by_status"] == {diagnostic: 1}


def test_missing_weights_and_duplicate_csv_exit_before_inference(fixture_args):
    args = fixture_args
    with patch.object(preflight, "has_expected_sha256", return_value=False):
        assert not preflight.prepare(args)
    assert coverage(args)["status"] == "blocked_model_assets"
    assert "vision_model_uint8.onnx" in coverage(args)["error"]
    args.run_dir = args.run_dir.with_name("duplicate-provenance")
    content = args.provenance.read_text(encoding="utf-8")
    args.provenance.write_text(content + content.splitlines()[1] + "\n", encoding="utf-8")
    assert not preflight.prepare(args)
    assert "CSV line 3" in coverage(args)["error"]


@pytest.mark.parametrize("condition, complete", [("complete", True), ("missing_row", False), ("changed_source", False)])
def test_post_run_demands_exact_coverage_and_unchanged_source(fixture_args, monkeypatch, condition, complete):
    args = fixture_args
    args.preflight_only = False

    def run_fixture(selected, directories, inference, team_id, weights):
        source = directories[0] / f"{VIDEO_ID}.MP4"
        outputs = inference / "predictions"
        outputs.mkdir(parents=True)
        (outputs / f"{VIDEO_ID}.json").write_text(json.dumps({
            "team_id": TEAM, "video_id": VIDEO_ID, "duration_sec": 30,
            "label": {"name": "cooking", "score": 0.8},
            "actions": [], "highlights": [{"segment": [2, 6]}],
        }), encoding="utf-8")
        if condition == "changed_source":
            source.write_bytes(b"different source fixture")
        rows = [] if condition == "missing_row" else [{"video_id": VIDEO_ID, "source": str(source), "status": "succeeded"}]
        return {"totals": {"succeeded": 1}, "videos": rows}

    monkeypatch.setattr(preflight, "run_manifest", run_fixture)
    assert preflight.prepare(args) is complete
    report = coverage(args)
    assert report["status"] == ("locally_complete" if complete else "incomplete")
    assert report["locally_validated"] == 1
    assert not report["submission_ready"]
    assert report["unverified_run_sources"] == ([] if complete else [VIDEO_ID])
    if complete:
        payload = {row["path"]: row["sha256"] for row in report["outputs"]}
        validate_coverage_receipt(args.run_dir / "coverage.json", 1, payload)
        with pytest.raises(ValueError, match="archive output hashes"):
            validate_coverage_receipt(args.run_dir / "coverage.json", 1, {next(iter(payload)): sha256(b"changed").hexdigest()})
    else:
        with pytest.raises(ValueError, match="complete approved local inference run"):
            validate_coverage_receipt(args.run_dir / "coverage.json", 1, {})


@pytest.mark.parametrize("arguments, expected", [([], 185), (["--full-manifest"], 187)])
def test_validator_cli_distinguishes_approved_scopes(tmp_path, arguments, expected):
    report = tmp_path.with_name(f"{tmp_path.name}-coverage.json")
    command = [sys.executable, "-B", str(ROOT / "validate_outputs.py"), "--output-dir", str(tmp_path),
               "--team-id", TEAM, "--report", str(report), *arguments]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    assert result.returncode == 1
    validation = json.loads(report.read_text(encoding="utf-8"))
    assert validation["eligible_count"] == expected
    assert len(validation["missing_ids"]) == expected
    assert not validation["passed"]
