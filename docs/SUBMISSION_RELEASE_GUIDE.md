# AURA release guide

AURA runs the frozen Day 3 CPU pipeline on an original first-person MP4 and returns an activity label, verb–noun actions, and selected highlight intervals in source seconds. The backend uses OpenAI CLIP ViT-B/32 through the pinned Xenova ONNX export. It targets 2 fps, uses two-second action windows, and compares 79 joint prompts against seven background prompts. An action requires two samples, a 0.015 cosine margin, and a 0.12 prompt-relative probability. The highlight planner uses visual and model evidence, with a 15% soft target and a minimum-first policy.

[Pipeline](ARCHITECTURE.md) · [Model and file digests](MODEL_WEIGHTS.json) · [Package status](../SUBMISSION_CHECKLIST.md)

## Requirements and delivery status

The student guide requests one prediction per original manifest video and an archive named for the registered team with the launcher, source, model files, dependencies, prediction directory, and README at the team folder root. This package follows the requested two Scuba exclusions, giving a local validation target of 185 from the original 187. The organizer material reviewed does not establish acceptance of a partial result set or clarify those exclusions.

The general presentation slides request a public or shared GitHub repository, reproducible README, Docker files, a `CollegeName_TeamName` deck in PPT or PDF, a demo link, and one final Google Form submission per registered team. Six-key `readme6` is the package profile drawn from the student guide. The supplied slides also contain a four-key example and conflicting deadline and demo-length statements. Confirm the team's registered identifier, repository URL, final form, and applicable instructions from its confirmation materials. [Organizer requirements and blockers](../SUBMISSION_CHECKLIST.md) · [Demo procedure](FINAL_SUBMISSION.md#demo-and-recording-procedure)

## Install and run

Use Python 3.12 and the packages pinned in `TEAM_ID/requirements.txt`. On Linux or WSL, run from the workspace root.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r TEAM_ID/requirements.txt
python -m pip check
python TEAM_ID/code/fetch_weights.py --weights-dir "$PWD/TEAM_ID/weights"

read -r -p 'Exact registered team ID: ' AURA_TEAM_ID
: "${AURA_TEAM_ID:?Enter the exact registered team ID}"
weights="$PWD/TEAM_ID/weights"
AURA_PROFILE=readme6 AURA_TEAM_ID="$AURA_TEAM_ID" AURA_WEIGHTS_DIR="$weights" \
  AURA_SAMPLE_FPS=2 AURA_ACTION_WINDOW_SECONDS=2 AURA_BUDGET_RATIO=0.15 \
  AURA_MIN_HIGHLIGHT_SECONDS=1 AURA_HIGHLIGHT_POLICY=minimum \
  PYTHON="$PWD/.venv/bin/python" \
  ./TEAM_ID/run.sh "/path/to/originals/VIDEO_ID.MP4" "runs/manual/predictions/VIDEO_ID.json"
```

On Windows the direct Python entry point runs the same pipeline. Use a fresh shell with the production defaults and follow the root README's PowerShell commands. The fetcher verifies the three pinned files and downloads missing or corrupt files. Inference checks the local hashes and can run offline.

Use the original untrimmed MP4 with its exact manifest stem for submission inference. OpenCV needs a decodable file and positive FPS and frame count. The runtime estimates duration from frame count divided by metadata FPS and approximates variable-frame-rate timing on that clock. Input size and runtime depend on the footage. There is no launcher range check tied to the kit’s typical two-to-ten-minute description. Manifest durations range from 11.13 to 1968.60 seconds. A source shorter than four seconds cannot satisfy the independent release checker’s minimum highlight requirement. [Platform commands](../README.md#run-one-authorized-original) · [Manifest and model details](MODELS_AND_DATA.md)

## Output contract

The selected profile writes exactly these top-level keys.

| Field | Value and local release check |
| --- | --- |
| `team_id` | Exact registered team ID from the team's organizer confirmation. Match it across files and the team folder. |
| `video_id` | Exact manifest ID and filename stem in `outputs/<video_id>.json`. |
| `duration_sec` | Positive finite number within 0.5 seconds of the manifest duration. |
| `label` | Object with `name` and `score`. EPIC requires `cooking`. FPVSum requires an exact FPVSum class or `other`. The bundled skiing class is `ski`. |
| `actions` | Array of zero to 2,000 objects, each with `segment`, `verb`, `noun` and `score`. Verb and noun must match the bundled taxonomy. |
| `highlights` | Nonempty array of objects with `segment` only. Intervals are chronological and nonoverlapping, and at least one lasts four seconds or longer. |

Each `segment` is `[start, end]` in seconds with at most two decimal places and `0 <= start < end <= duration_sec + 0.5`. Scores are finite numbers from 0 to 1. A shorter additional highlight or a sum over 15% produces a local warning. The packaged taxonomy stays in `code/resources/supported_classes.json`. The archived `skiing_03.json` example has both a label inconsistency and an off-manifest ID. A frozen model output can fail a dataset-specific label check. Review the source and validator result without relabeling the prediction. [Independent validator](../validate_outputs.py) · [Architecture](ARCHITECTURE.md#serialization-validation-and-errors)

## Generate and check a batch

The batch wrapper requires Linux or WSL to report peak RSS. Stage authorized, provenance-verified originals in flat folders, with one case-exact stem per video. Omit unavailable folders and use one `--media-dir` argument per existing folder. The wrapper filters `Scuba_KD74Ywuy9ng` and `Scuba_Um4kqB8bQBg`. It does not acquire or authenticate media.

```bash
: "${AURA_TEAM_ID:?Enter the exact registered team ID}"
run=runs/track4-submission
python examples/run_release_inference.py \
  --media-dir /path/to/verified/epic-originals \
  --media-dir /path/to/verified/fpvsum-originals \
  --weights "$PWD/TEAM_ID/weights" --team-id "$AURA_TEAM_ID" --run-dir "$run"
```

Use a fresh run directory. Exit 1 means the run is incomplete. Check `inference/processing-report.json` for missing or ambiguous files, duration mismatches, launcher failures, and validation errors. Only successful, locally checked predictions land in `inference/predictions/`.

```bash
python validate_outputs.py --output-dir "$run/inference/predictions" \
  --team-id "$AURA_TEAM_ID" --report "$run/strict-validation.json"
```

For an available subset, add `--allow-missing` and choose a different report filename. Every mandatory per-file rule still applies. Keep experimental, archived QA, and demo outputs outside the release prediction directory. The student kit references an official `validate.py`, which was absent from the supplied archive.

## Build an organizer-facing ZIP

This step requires a Git checkout that contains the intended source commit, the exact registered team ID, and the checked prediction set. The active workspace is a source export. A frozen archive records Track 4 source commit `6a5f8956c4eeef1a9bdcdb78326340359337b9a9`, which is distinct from an active repository HEAD. Check the package report for the actual Git verification and available handoff.

Run the following in the verified checkout using the release packager, with paths adjusted to the real run and assets. The active workspace's revised packager preserves the Git archive’s file bytes and executable modes across platforms.

```bash
source_commit=6a5f8956c4eeef1a9bdcdb78326340359337b9a9
git cat-file -t "$source_commit"
python examples/build_release_submission.py \
  --output "$run/$AURA_TEAM_ID.zip" --team-id "$AURA_TEAM_ID" \
  --predictions "$run/inference/predictions" --weights "$PWD/TEAM_ID/weights" \
  --license-file licenses/OpenAI-CLIP-MIT.txt --source-commit "$source_commit"
```

The default packager requires the full eligible output set. A package created with `--allow-missing` visibly records its missing predictions. The source handoff can support local setup and reproduction while the final requirements are being resolved. The full workspace has the archive checksum and provenance in `SUBMISSION_PACKAGE_REPORT.md`. [Source handoff and release blockers](../SUBMISSION_CHECKLIST.md)

The model manifest pins the Xenova conversion and the three asset hashes. The included OpenAI CLIP MIT license comes from upstream commit `d05afc436d78f1c48dc0dbf8e5980a9d471f35f6` and has SHA-256 `987e63b32f6c89ff5160e429458a872ff048e6860b590a3912e938f9da8f14db`. [Weight manifest](MODEL_WEIGHTS.json) · [License](../licenses/OpenAI-CLIP-MIT.txt)

## Evaluation and limitations

Local action mAP, action coverage, and replay checks describe specific recorded subsets. The larger development ranking study and audit cover aggregate scores and proposal geometry. Raw classifier vectors and some individual decisions were unavailable for retrospective reconstruction. They provide development evidence while model behavior remains frozen.

Official organizer acceptance, metrics, and exact scoring conventions remain unverified. FPV source renditions need organizer alignment before treating them as submission inputs. The model has sparse action vocabulary coverage, can abstain on actions, and provides coarse two-second boundaries. CLIP scores are uncalibrated. Camera motion can influence highlight importance, and variable-rate timing can differ from source presentation timestamps. The full workspace retains the local metric definitions and expanded study audit. [Model and duration details](MODELS_AND_DATA.md)
