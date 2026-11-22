# AURA Track 4 release

AURA converts an original first-person MP4 into an activity label, time-stamped verb–noun actions and nonoverlapping highlight intervals. It keeps the selected moments on the source timeline so reviewers can seek to them in the original footage. These commands apply inside an organizer-facing ZIP built by the release packager. The workspace source handoff has separate setup notes in its root README.

## Setup and run

Run from the extracted team directory on Linux or WSL with Python 3.12 and Bash. The ZIP name and `RELEASE.json` identify the source commit and the exact registered team ID.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check

team="$(python -c 'import json; print(json.load(open("RELEASE.json", encoding="utf-8"))["team_id"])')"
test -n "$team" && test "$(basename "$PWD")" = "$team" || exit 1
AURA_TEAM_ID="$team" AURA_PROFILE=readme6 PYTHON="$PWD/.venv/bin/python" \
  AURA_WEIGHTS_DIR="$PWD/weights" AURA_SAMPLE_FPS=2 AURA_ACTION_WINDOW_SECONDS=2 \
  AURA_BUDGET_RATIO=0.15 AURA_MIN_HIGHLIGHT_SECONDS=1 AURA_HIGHLIGHT_POLICY=minimum \
  ./run.sh "/path/to/originals/VIDEO_ID.MP4" "outputs/VIDEO_ID.json"
```

The pinned weights in `weights/` are checked by SHA-256 on model initialization. To repair missing or corrupted weight files, run `python code/fetch_weights.py --weights-dir weights` with network access. Inference reads local weights. The three pinned model files and their origin are recorded in `weights/` alongside the license.

## Production model

The CPU runner uses the pinned CLIP ViT-B/32 ONNX model, 2 fps sampling, two-second action windows, 79 action pairs and seven background prompts. It keeps the original Day 3 score and margin gates. The pipeline decodes frames, encodes them with CLIP, ranks action prompts per window, estimates importance and selects highlights. Weak action evidence can yield an empty action array. The Day 4 and TSM experiment entry points and checkpoints belong to the research archive.

## Output structure

The six required keys are `team_id`, `video_id`, `duration_sec`, `label`, `actions` and `highlights`. The label has `name` and `score`, an action has `segment`, `verb`, `noun` and `score`, and a highlight has `segment`. Segment endpoints are seconds. Use canonical vocabulary in `code/resources/supported_classes.json`, including `ski`.

Output names must be `<video_id>.json`. Each output needs a highlight of at least four seconds. Highlights are sorted and do not overlap. The 15% total budget is treated as a soft target. When 15% is less than four seconds, the Day 3 minimum-first policy may emit a four-second highlight and report a budget warning.

## Validate the outputs

```bash
python validate_outputs.py --output-dir outputs --team-id "$team"
```

The strict local check requires all eligible outputs. To check the files from an available-media subset, add `--allow-missing`. That still checks every mandatory per-file rule and reports each missing ID. The organizer-facing `validate.py` was absent from the student archive.

The student guide requests predictions for all 187 manifest IDs. The local release workflow targets 185 after the requested exclusions of `Scuba_KD74Ywuy9ng` and `Scuba_Um4kqB8bQBg`. Check `RELEASE.json` for the package's actual generated and missing counts. Missing sources have no prediction. The source handoff inventory identified `P06_11` as the one currently usable unsealed EPIC original. Registered-team inference remained pending the real team ID. The Day 3 EPIC replay reported 0.294% local mean action mAP across tIoU 0.10–0.50 on 11 archived videos. This is a local proxy on a named subset. Organizer acceptance and official competition scores remain unverified.
