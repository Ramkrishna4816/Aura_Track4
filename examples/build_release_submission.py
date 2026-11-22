#!/usr/bin/env python3
"""Build the organizer-facing Track 4 ZIP from a committed source snapshot."""
from __future__ import annotations

import argparse
from hashlib import sha256
from io import BytesIO
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import subprocess
import sys
from tarfile import open as open_tar
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
CLIP_LICENSE_SHA256 = "987e63b32f6c89ff5160e429458a872ff048e6860b590a3912e938f9da8f14db"
WEIGHT_NAMES = ("vision_model_uint8.onnx", "text_model_uint8.onnx", "tokenizer.json")
INPUTS = {
    "TEAM_ID/run.sh": "run.sh",
    "TEAM_ID/code": "code",
    "TEAM_ID/requirements.txt": "requirements.txt",
    "docs/SUBMISSION_PACKAGE_README.md": "README.md",
    "docs/MODEL_WEIGHTS.json": "weights/MODEL_WEIGHTS.json",
    "validate_outputs.py": "validate_outputs.py",
}
ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def stage_committed_source(commit: str, destination: Path) -> dict[str, int]:
    """Stage the organizer-facing files and retain their archived modes."""
    kind = subprocess.run(
        ["git", "cat-file", "-t", commit], cwd=ROOT, capture_output=True, check=True,
    )
    if kind.stdout.strip() != b"commit":
        raise ValueError("source SHA must identify a Git commit")
    result = subprocess.run(
        ["git", "-c", "core.autocrlf=false", "-c", "core.eol=lf", "archive", "--format=tar", commit, *INPUTS],
        cwd=ROOT, capture_output=True, check=True,
    )
    modes = {}
    with open_tar(fileobj=BytesIO(result.stdout), mode="r:") as source:
        for entry in source.getmembers():
            if entry.isdir():
                continue
            path = INPUTS.get(entry.name)
            if path is None and entry.name.startswith("TEAM_ID/code/"):
                path = entry.name.removeprefix("TEAM_ID/")
            if not entry.isfile() or path is None:
                raise ValueError(f"unsupported entry in committed source: {entry.name}")
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.extractfile(entry) as contents, target.open("xb") as output:
                shutil.copyfileobj(contents, output)
            target.chmod(entry.mode & 0o777)
            modes[path] = 0o755 if entry.mode & 0o111 else 0o644
    return modes


def stage_predictions(source: Path, destination: Path) -> None:
    """Snapshot prediction bytes before validation so the ZIP uses the checked files."""
    destination.mkdir()
    for entry in sorted(source.iterdir()):
        if entry.name == ".gitkeep" and entry.is_file() and not entry.is_symlink():
            continue
        if entry.suffix.lower() != ".json" or entry.is_symlink() or not entry.is_file():
            raise ValueError(f"unexpected entry in the prediction directory: {entry.name}")
        shutil.copyfile(entry, destination / entry.name)
    if not any(destination.iterdir()):
        raise ValueError("at least one validated prediction is required")


def validate_snapshot(package: Path, team_id: str, *, allow_missing: bool) -> dict:
    """Run the archived independent validator from its final package layout."""
    report = package.parent / "validation.json"
    command = [
        sys.executable, "-B", str(package / "validate_outputs.py"),
        "--output-dir", str(package / "outputs"), "--team-id", team_id,
        "--report", str(report),
    ]
    if allow_missing:
        command.append("--allow-missing")
    result = subprocess.run(command, cwd=package, capture_output=True, text=True)
    if result.returncode:
        raise ValueError(f"prediction validation failed\n{result.stdout}{result.stderr}".rstrip())
    return json.loads(report.read_text(encoding="utf-8"))


def stage_model_notice(package: Path, license_path: Path) -> dict[str, dict]:
    """Bundle the original copyright notice and the pinned model manifest."""
    notice_path = package / "weights" / "MODEL_WEIGHTS.json"
    notice = json.loads(notice_path.read_text(encoding="utf-8"))
    artifacts = {artifact["file"]: artifact for artifact in notice["artifacts"]}
    if len(notice["artifacts"]) != len(WEIGHT_NAMES) or set(artifacts) != set(WEIGHT_NAMES):
        raise ValueError("the committed model manifest does not describe the three pinned CLIP files")
    license_bytes = license_path.read_bytes()
    license_digest = sha256(license_bytes).hexdigest()
    if license_digest != CLIP_LICENSE_SHA256:
        raise ValueError("the OpenAI CLIP MIT license does not match its pinned SHA-256")
    (notice_path.parent / "CLIP-LICENSE.txt").write_bytes(license_bytes)
    notice["deployment"] = "Pinned, verified CLIP artifacts are bundled in this submission."
    notice["bundled_license_file"] = "CLIP-LICENSE.txt"
    notice["bundled_license_sha256"] = license_digest
    notice_path.write_text(json.dumps(notice, indent=2) + "\n", encoding="utf-8")
    return artifacts


def zip_entry(path: str, mode: int = 0o644) -> ZipInfo:
    entry = ZipInfo(path, date_time=ZIP_TIME)
    entry.create_system = 3
    entry.external_attr = (0o100000 | mode) << 16
    entry.compress_type = ZIP_DEFLATED
    return entry


def add_weight(archive: ZipFile, team_id: str, path: Path, expected: dict) -> None:
    """Stream a single weight into the ZIP and hash the bytes actually written."""
    if path.stat().st_size != expected["bytes"]:
        raise ValueError(f"wrong byte length for CLIP artifact {path.name}")
    digest = sha256()
    with path.open("rb") as source, archive.open(zip_entry(f"{team_id}/weights/{path.name}"), "w") as target:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
            target.write(block)
    if digest.hexdigest() != expected["sha256"]:
        raise ValueError(f"SHA-256 mismatch for CLIP artifact {path.name}")


def build_release(
    *, output: Path, predictions: Path, team_id: str, weights: Path,
    license_file: Path, source_commit: str, allow_missing: bool = False,
) -> dict:
    """Publish the validated ZIP without replacing an existing file."""
    if (not team_id or team_id.strip() != team_id or team_id.endswith(".")
            or any(char in '<>:"/\\|?*' or ord(char) < 32 for char in team_id)
            or PureWindowsPath(team_id).is_reserved()):
        raise ValueError("team ID must be one portable folder name")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", source_commit):
        raise ValueError("source commit must be a full 40-character SHA")
    source_commit = source_commit.lower()
    if output.suffix.lower() != ".zip":
        raise ValueError("--output must have a .zip extension")
    if os.path.lexists(output):
        raise FileExistsError(f"release ZIP already exists: {output}")
    if output.resolve().is_relative_to(predictions.resolve()):
        raise ValueError("release ZIP must be outside the prediction directory")

    with tempfile.TemporaryDirectory(prefix=".release-", dir=output.parent) as work:
        staging = Path(work)
        package = staging / "package"
        source_modes = stage_committed_source(source_commit, package)
        stage_predictions(predictions, package / "outputs")
        validation = validate_snapshot(package, team_id, allow_missing=allow_missing)
        if (validation["manifest_count"] != 187 or validation["eligible_count"] != 185
                or len(validation["excluded_from_manifest"]) != 2):
            raise ValueError("expected the 187-entry organizer manifest with two exclusions")
        model_artifacts = stage_model_notice(package, license_file)
        metadata = {
            "source_commit": source_commit,
            "team_id": team_id,
            "official_validator_run": False,
            "allow_missing": allow_missing,
            "partial_submission": bool(validation["missing_ids"]),
            "local_validation": validation,
        }
        (package / "RELEASE.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        candidate = staging / "submission.zip"
        with ZipFile(candidate, "w", compression=ZIP_DEFLATED) as archive:
            for path in sorted(package.rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(package).as_posix()
                member = f"{team_id}/{relative}"
                archive.writestr(zip_entry(member, source_modes.get(relative, 0o644)), path.read_bytes())
            for name in WEIGHT_NAMES:
                add_weight(archive, team_id, weights / name, model_artifacts[name])
        candidate.chmod(0o644)
        os.link(candidate, output)
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("output", "predictions", "weights", "license-file"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--team-id", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--allow-missing", action="store_true", help="build a partial package")
    args = parser.parse_args()
    try:
        build_release(**vars(args))
    except subprocess.CalledProcessError as exc:
        parser.exit(1, f"could not read committed source: {exc.stderr.decode('utf-8', 'replace')}")
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"could not build release: {exc}\n")
    print(f"Built {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
