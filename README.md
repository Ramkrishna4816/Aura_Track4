# AURA — Action Understanding & Relevance-based Autonomous Summarization

**Samsung PRISM XR Hackathon 2026 · Track 4: Action-Aware Video Summarization**

AURA is a first-person video summarization prototype that converts an MP4 video into three outputs:

- **Activity recognition:** an overall activity label.
- **Action understanding:** temporally localized verb–noun action predictions.
- **Highlight extraction:** selected intervals from the original video timeline.

The goal is to make first-person video easier to understand by identifying what is happening, when it happens, and which moments are worth watching.

---

## 1. How AURA works

AURA uses OpenAI CLIP ViT-B/32 through ONNX Runtime for CPU-based visual inference.

The frozen production pipeline uses:

| Component | Configuration |
|---|---|
| Visual encoder | CLIP ViT-B/32 |
| Inference runtime | ONNX Runtime |
| Execution | CPU |
| Frame sampling | 2 FPS |
| Action analysis | 2-second windows |
| Action representation | Verb–noun pairs |
| Highlight selection | Original highlight planner |
| Output profile | `readme6` |
| Highlight budget | 15% soft target |

### Processing pipeline

1. **Video input:** Read the first-person MP4 and its duration.
2. **Frame sampling:** Sample frames at 2 FPS.
3. **Visual representation:** Extract visual features using the pinned CLIP model.
4. **Activity recognition:** Estimate the overall activity label.
5. **Action prediction:** Evaluate candidate verb–noun descriptions over temporal windows.
6. **Highlight selection:** Select relevant intervals on the original video timeline.
7. **Serialization:** Generate structured JSON output and validate it against the configured schema.

The system preserves original-video timestamps rather than creating a separate edited timeline.

---

## 2. Output format

Each prediction uses six top-level JSON keys:

- `team_id`
- `video_id`
- `duration_sec`
- `label`
- `actions`
- `highlights`

Example structure:

```json
{
  "team_id": "TEAM_ID",
  "video_id": "VIDEO_ID",
  "duration_sec": 120.0,
  "label": {
    "name": "cooking",
    "score": 0.85
  },
  "actions": [
    {
      "segment": [12.0, 14.0],
      "verb": "cut",
      "noun": "vegetable",
      "score": 0.72
    }
  ],
  "highlights": [
    {
      "segment": [10.0, 16.0]
    }
  ]
}
```

*The values above illustrate the schema only; they are not measured AURA predictions.*

AURA can return an empty action list while still selecting highlights.

The highlight budget is a soft target. A valid submission must also satisfy the competition's minimum highlight-duration requirement of four seconds.

[Full output contract](docs/SUBMISSION_RELEASE_GUIDE.md#output-contract)

---

## 3. Repository structure

```text
AURA/
├── TEAM_ID/
│   ├── code/
│   │   ├── aura/
│   │   ├── run_aura.py
│   │   └── fetch_weights.py
│   ├── resources/
│   ├── weights/
│   ├── outputs/
│   ├── requirements.txt
│   ├── Dockerfile
│   └── run.sh
├── docs/
│   ├── ARCHITECTURE.md
│   ├── MODELS_AND_DATA.md
│   ├── SUBMISSION_RELEASE_GUIDE.md
│   └── FINAL_SUBMISSION.md
├── examples/
├── evaluation/
├── licenses/
├── validate_outputs.py
├── SUBMISSION_CHECKLIST.md
└── README.md
```

---

## 4. Setup

### Requirements

- Python 3.12
- Linux or WSL recommended for the supplied Bash batch workflow
- Windows PowerShell supported for individual-video inference
- Dependencies listed in `TEAM_ID/requirements.txt`

### Linux / WSL

Run commands separately from the repository root:

```bash
python3.12 -m venv .venv
source .venv/bin/activate

python -m pip install -r TEAM_ID/requirements.txt
python -m pip check

python TEAM_ID/code/fetch_weights.py
```

The setup script retrieves the three SHA-256-pinned model assets. Inference uses the local copies.

### Windows PowerShell

```powershell
py -3.12 -m venv .venv

$python = ".\.venv\Scripts\python.exe"

& $python -m pip install -r TEAM_ID/requirements.txt
& $python -m pip check

& $python TEAM_ID/code/fetch_weights.py
```

---

## 5. Run inference

Use an authorized original video and its exact manifest video ID as the filename stem.

### Windows PowerShell example

```powershell
$python = ".\.venv\Scripts\python.exe"

$env:AURA_TEAM_ID = Read-Host "Enter organizer-confirmed team ID"

if ([string]::IsNullOrWhiteSpace($env:AURA_TEAM_ID)) {
    throw "A valid team ID is required."
}

$env:AURA_PROFILE = "readme6"
$env:AURA_WEIGHTS_DIR = (Resolve-Path "TEAM_ID/weights").Path
$env:AURA_SAMPLE_FPS = "2"
$env:AURA_ACTION_WINDOW_SECONDS = "2"
$env:AURA_BUDGET_RATIO = "0.15"
$env:AURA_MIN_HIGHLIGHT_SECONDS = "4"
$env:AURA_HIGHLIGHT_POLICY = "minimum"

& $python TEAM_ID/code/run_aura.py `
    "C:\videos\VIDEO_ID.MP4" `
    "runs/manual/predictions/VIDEO_ID.json"
```

Replace the example paths and team ID with the actual authorized values.

**Important:** The team identifier must be confirmed by the organizer. Do not assume that the team name and the required JSON `team_id` are interchangeable.

For batch inference, refer to the release guide.

[Batch inference and packaging](docs/SUBMISSION_RELEASE_GUIDE.md#generate-and-check-a-batch)

---

## 6. Validate predictions

After generating predictions, run:

```powershell
& $python validate_outputs.py `
    --output-dir runs/manual/predictions `
    --team-id $env:AURA_TEAM_ID `
    --allow-missing
```

The subset validation checks individual prediction files, including schema, taxonomy, timestamps and team ID.

Use strict validation for a complete required prediction set.

[Validation and submission instructions](docs/SUBMISSION_RELEASE_GUIDE.md)

---

## 7. Evaluation and evidence

AURA has undergone local development experiments, regression testing and an independent audit of archived evaluation

## Development dashboard

The six-video dashboard compares the frozen stock outputs and opt-in factorized-refined outputs from one public EPIC-KITCHENS development run. The dashboard tools are released as an engineering update. Competition submission still requires the registered team identifier, organizer-confirmed scope and original media coverage. [Dashboard setup and scope](docs/DEVELOPMENT_DASHBOARD.md)
