"""Assemble a local AURA source handoff without substituting for the organizer submission."""

from __future__ import annotations

import argparse
from hashlib import file_digest, sha256
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from examples.build_release_submission import CLIP_LICENSE_SHA256, WEIGHT_NAMES, add_weight, zip_entry

REFERENCE_SHA256 = "90aea46561b73ff3e5935414bc153c35af7ffde9dc4029093612e930a6a89865"
REFERENCE_COMMIT = "6a5f8956c4eeef1a9bdcdb78326340359337b9a9"
ARCHIVE_ROOT = "AURA"
TEAM_PREFIX = "AURA/TEAM_ID/"
TEAM_EXCLUDES = {"outputs", "weights", "__pycache__"}
HANDOFF_FILES = (
    ".gitattributes",
    ".gitignore",
    "README.md",
    "SUBMISSION_CHECKLIST.md",
    "TEAM_ID/outputs/.gitkeep",
    "docs/ARCHITECTURE.md",
    "docs/FINAL_SUBMISSION.md",
    "docs/MODELS_AND_DATA.md",
    "docs/MODEL_WEIGHTS.json",
    "docs/SUBMISSION_PACKAGE_README.md",
    "docs/SUBMISSION_RELEASE_GUIDE.md",
    "evaluation/tsm/measure_command.py",
    "examples/build_release_submission.py",
    "examples/build_source_handoff.py",
    "examples/make_smoke_video.py",
    "examples/run_manifest.py",
    "examples/run_release_inference.py",
    "licenses/OpenAI-CLIP-MIT.txt",
    "validate_outputs.py",
)


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return file_digest(handle, "sha256").hexdigest()


def frozen_source(reference: Path) -> dict[str, tuple[bytes, int]]:
    if digest(reference) != REFERENCE_SHA256:
        raise ValueError("frozen release archive SHA-256 differs from the audited reference")
    files = {}
    with ZipFile(reference) as archive:
        if archive.comment != REFERENCE_COMMIT.encode("ascii"):
            raise ValueError("frozen release archive comment differs from the audited source SHA")
        for member in archive.infolist():
            if member.is_dir() or not member.filename.startswith(TEAM_PREFIX):
                continue
            relative = Path(member.filename.removeprefix(TEAM_PREFIX))
            if TEAM_EXCLUDES.intersection(relative.parts):
                continue
            name = f"TEAM_ID/{relative.as_posix()}"
            live = ROOT / name
            content = archive.read(member)
            if live.is_symlink() or not live.is_file() or live.read_bytes() != content:
                raise ValueError(f"production source differs from the audited reference: {name}")
            mode = 0o755 if (member.external_attr >> 16) & 0o111 else 0o644
            files[name] = (content, mode)
        model_name = "docs/MODEL_WEIGHTS.json"
        pinned_model = archive.read(f"{ARCHIVE_ROOT}/{model_name}")
        if (ROOT / model_name).read_bytes() != pinned_model:
            raise ValueError("model manifest differs from the audited reference")
    team = ROOT / "TEAM_ID"
    live_names = {
        path.relative_to(ROOT).as_posix()
        for path in team.rglob("*")
        if path.is_file() and not TEAM_EXCLUDES.intersection(path.relative_to(team).parts)
    }
    if set(files) != live_names or files["TEAM_ID/run.sh"][1] != 0o755:
        raise ValueError("production file set or launcher mode differs from the audited reference")
    files[model_name] = (pinned_model, 0o644)
    return files


def build_handoff(output: Path, reference: Path) -> None:
    if output.suffix.lower() != ".zip" or os.path.lexists(output):
        raise ValueError("output must be a new .zip file")
    files = frozen_source(reference)
    for name in HANDOFF_FILES:
        if name in files:
            continue
        path = ROOT / name
        if path.is_symlink():
            raise ValueError(f"unexpected symlink: {name}")
        files[name] = (path.read_bytes(), 0o644)
    # Keep the batch-guide link in the byte-preserved TEAM_ID README usable.
    files["docs/DAY3_STUDENT_KIT.md"] = (
        b"# Batch setup and reporting\n\n"
        b"The current commands are in the [release guide]"
        b"(SUBMISSION_RELEASE_GUIDE.md#generate-and-check-a-batch).\n",
        0o644,
    )
    model = json.loads(files["docs/MODEL_WEIGHTS.json"][0])
    weights = {item["file"]: item for item in model["artifacts"]}
    if len(model["artifacts"]) != len(WEIGHT_NAMES) or set(weights) != set(WEIGHT_NAMES):
        raise ValueError("expected exactly the three pinned CLIP assets")
    if sha256(files["licenses/OpenAI-CLIP-MIT.txt"][0]).hexdigest() != CLIP_LICENSE_SHA256:
        raise ValueError("the packaged CLIP license does not match its pinned digest")

    with TemporaryDirectory(prefix=".handoff-", dir=output.parent) as work:
        candidate = Path(work) / "handoff.zip"
        with ZipFile(candidate, "w", compression=ZIP_DEFLATED) as archive:
            hashes = {}
            for name, (content, mode) in sorted(files.items()):
                archive.writestr(zip_entry(f"{ARCHIVE_ROOT}/{name}", mode), content)
                hashes[name] = sha256(content).hexdigest()
            for name in sorted(weights):
                path = ROOT / "TEAM_ID/weights" / name
                add_weight(archive, f"{ARCHIVE_ROOT}/TEAM_ID", path, weights[name])
                hashes[f"TEAM_ID/weights/{name}"] = weights[name]["sha256"]
            receipt = {
                "purpose": "local source handoff for a later authorized submission",
                "ready_for_organizer_submission": False,
                "frozen_reference_archive_sha256": REFERENCE_SHA256,
                "frozen_reference_archive_commit_comment": REFERENCE_COMMIT,
                "current_checkout_commit_attested": False,
                "registered_team_id": None,
                "prediction_count": 0,
                "sha256": hashes,
            }
            archive.writestr(zip_entry(f"{ARCHIVE_ROOT}/SOURCE_HANDOFF.json"),
                             json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        os.link(candidate, output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="new ZIP path in an existing directory")
    parser.add_argument("--frozen-archive", required=True, type=Path, help="the audited Track 4 source reference ZIP")
    args = parser.parse_args()
    try:
        build_handoff(args.output, args.frozen_archive)
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(1, f"could not build source handoff: {exc}\n")
    print(f"Built local source handoff {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
