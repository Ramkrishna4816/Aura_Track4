# AURA · Action Understanding & Relevance-based Autonomous Summarization

AURA summarizes a first-person MP4 as an activity label, detected verb–noun action intervals, and highlights on the original timeline. It is a Samsung PRISM XR Hackathon 2026 Track 4 prototype. The frozen release runs OpenAI CLIP ViT-B/32 through ONNX Runtime on CPU.

The release uses 2 fps sampling, two-second action windows, the original highlight planner, and the six-key `readme6` output profile. The manifest has 187 IDs. The local workflow targets 185 after the two requested Scuba exclusions. The source handoff contains the runnable code and pinned assets. Registered-team predictions remain pending the actual team ID and approved originals.

[Release guide](docs/SUBMISSION_RELEASE_GUIDE.md) · [Submission checklist](SUBMISSION_CHECKLIST.md)

The full workspace records the verification and archive checksum in `SUBMISSION_PACKAGE_REPORT.md`.

## Run one authorized original

Use Python 3.12 and the pinned dependencies. On Linux or WSL, run from this directory with Bash. Give the input its exact manifest stem for submission use.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r TEAM_ID/requirements.txt
python -m pip check
python TEAM_ID/code/fetch_weights.py
read -r -p 'Exact registered team ID: ' AURA_TEAM_ID
: "${AURA_TEAM_ID:?Enter the exact registered team ID}"
AURA_PROFILE=readme6 AURA_TEAM_ID="$AURA_TEAM_ID" PYTHON="$PWD/.venv/bin/python" \
  AURA_WEIGHTS_DIR="$PWD/TEAM_ID/weights" AURA_SAMPLE_FPS=2 AURA_ACTION_WINDOW_SECONDS=2 \
  AURA_BUDGET_RATIO=0.15 AURA_MIN_HIGHLIGHT_SECONDS=1 AURA_HIGHLIGHT_POLICY=minimum \
  ./TEAM_ID/run.sh "/path/to/originals/VIDEO_ID.MP4" "runs/manual/predictions/VIDEO_ID.json" &&
python validate_outputs.py --output-dir runs/manual/predictions --team-id "$AURA_TEAM_ID" --allow-missing
```

On Windows PowerShell, launch the same frozen Python entry point. The Linux batch runner provides the full manifest workflow and records per-video peak memory.

```powershell
py -3.12 -m venv .venv
$python = '.\.venv\Scripts\python.exe'
& $python -m pip install -r TEAM_ID/requirements.txt
& $python TEAM_ID/code/fetch_weights.py
$env:AURA_TEAM_ID = Read-Host 'Exact registered team ID'
if ([string]::IsNullOrWhiteSpace($env:AURA_TEAM_ID)) { throw 'The registered team ID is required' }
$env:AURA_PROFILE = 'readme6'
$env:AURA_WEIGHTS_DIR = (Resolve-Path TEAM_ID/weights).Path
$env:AURA_SAMPLE_FPS = '2'
$env:AURA_ACTION_WINDOW_SECONDS = '2'
$env:AURA_BUDGET_RATIO = '0.15'
$env:AURA_MIN_HIGHLIGHT_SECONDS = '1'
$env:AURA_HIGHLIGHT_POLICY = 'minimum'
& $python TEAM_ID/code/run_aura.py 'C:\videos\VIDEO_ID.MP4' 'runs/manual/predictions/VIDEO_ID.json'
if ($LASTEXITCODE -eq 0) {
    & $python validate_outputs.py --output-dir runs/manual/predictions --team-id $env:AURA_TEAM_ID --allow-missing
}
```

Setup fetches three SHA-256-pinned CLIP assets. Inference uses these local files. Reserve output paths under a fresh run directory. The local subset check still enforces the per-file schema, taxonomy, timestamps, team ID and four-second highlight minimum. Use the strict check for a complete set. [Batch inference and packaging](docs/SUBMISSION_RELEASE_GUIDE.md#generate-and-check-a-batch) · [Model manifest](docs/MODEL_WEIGHTS.json)

## Output and evidence

The JSON keys are `team_id`, `video_id`, `duration_sec`, `label`, `actions` and `highlights`. Scores describe relative prompt support. AURA can return an empty action list and still select useful highlights. The 15% highlight budget is a soft target and a valid output needs at least one interval of four seconds or longer. [Full schema and rules](docs/SUBMISSION_RELEASE_GUIDE.md#output-contract) · [Pipeline and limitations](docs/ARCHITECTURE.md) · [Models and data](docs/MODELS_AND_DATA.md)

The archived measurements are local diagnostics on named subsets. Official organizer validation and competition scores remain unverified. The expanded study used six development videos, and its independent audit verified aggregate scoring and proposal geometry from the archived evidence. The workspace retains `docs/FINAL_VALIDATION_METRICS.md` and `evaluation/EXPANDED_STUDY_INDEPENDENT_AUDIT.md`.

## Project layout

| Path | Contents |
| --- | --- |
| `TEAM_ID/` | Frozen launcher, model code, requirements, taxonomy and manifest |
| `examples/` | Smoke-video generator, manifest runner and release packager |
| `tests/` | Tests and archived example fixtures in the full workspace |
| `docs/` | Architecture, setup, release guides and research history |
| `evaluation/` | Local diagnostics, provenance and research evidence in the full workspace |

[Demo and recording procedure](docs/FINAL_SUBMISSION.md#demo-and-recording-procedure)
