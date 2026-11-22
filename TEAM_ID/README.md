# AURA submission package

AURA accepts a first-person MP4 and writes one locally validated JSON file. It uses a pretrained OpenAI CLIP ViT-B/32 image and text encoder to label the video and score a limited vocabulary of paired actions. Motion, transitions, novelty, and the model's evidence rank intervals from the original video.

## Setup

Use Python 3.11 or 3.12 in a virtual environment. CPU inference needs OpenCV, NumPy, Pillow, the model tokenizer, and ONNX Runtime. From this directory on Linux or WSL, run the following commands.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python code/fetch_weights.py
./run.sh "/path/to/input.mp4" "outputs/input.json"
```

In PowerShell, the direct Python entry point uses the same pipeline.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe code\fetch_weights.py
.\.venv\Scripts\python.exe code\run_aura.py "C:\videos\input.mp4" "outputs\input.json"
```

In Git Bash on Windows, a virtual environment created by Windows Python uses `Scripts/`. After the PowerShell setup, the shell launcher can use that interpreter with `PYTHON=./.venv/Scripts/python.exe ./run.sh input.mp4 outputs/input.json`.

The weight setup needs network access and downloads about 155 MB of pinned ONNX artifacts to `weights/`. Run the fetch command before offline inference. To fetch into a shared or persistent directory, pass `python code/fetch_weights.py --weights-dir /path/to/aura-weights` and set `AURA_WEIGHTS_DIR` to that directory when running inference. Linux launcher arguments resolve relative to the caller's working directory. Quote paths containing spaces.

## Docker

After the setup above, build from the project root on Linux or WSL. The following command mounts the local weights and input read-only and writes predictions to a separate host directory.

```bash
docker build -t aura-track4 TEAM_ID
mkdir -p "$PWD/docker-outputs"
docker run --rm --user "$(id -u):$(id -g)" -e AURA_TEAM_ID=demo \
  --mount "type=bind,source=$PWD/TEAM_ID/weights,target=/app/weights,readonly" \
  --mount "type=bind,source=/absolute/path/to/videos,target=/input,readonly" \
  --mount "type=bind,source=$PWD/docker-outputs,target=/output" \
  aura-track4 /input/input.mp4 /output/input.json
```

The UID and GID options match host ownership with a standard Docker daemon. If you run a rootless daemon as your current user, omit `--user "$(id -u):$(id -g)"` to use that daemon's host UID mapping. The selected container user needs read access to the weights and video plus write access to the output mount.

For a network that uses a custom CA, pass its PEM bundle to the build with `--secret id=proxy_ca,src=/path/to/ca-bundle.pem`.

For Google Colab, upload or mount the project files and install the same runtime requirements in a CPU runtime. Use the Python entry point with Colab paths. Weights stored on a persistent mounted drive can be reused by setting `AURA_WEIGHTS_DIR`.

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `AURA_PROFILE` | Serialization profile, either `readme6` or `slide4` | `readme6`, pending organizer confirmation |
| `AURA_TEAM_ID` | Team identifier for `readme6` | Submission directory name |
| `AURA_WEIGHTS_DIR` | Directory containing the pinned model artifacts | `weights/` beside `run.sh` |
| `AURA_SAMPLE_FPS` | Sampled frames per second; positive and finite | 2.0 |
| `AURA_BUDGET_RATIO` | Target total highlight length as a source-duration fraction in (0, 1] | 0.15 |
| `AURA_MIN_HIGHLIGHT_SECONDS` | Local minimum candidate length before budget and profile adjustment | 1.0 |
| `AURA_HIGHLIGHT_POLICY` | `minimum` preserves a four-second `readme6` highlight when the source fits it; `budget` prioritizes the budget | `minimum` |
| `PYTHON` | Interpreter executable for `run.sh` | First working `python3` or `python` on `PATH` |

The video identifier comes from the input filename stem. Preserve the manifest ID when naming an input and its corresponding output. The taxonomy ships with the code and is the same for both evaluation datasets. For example, to select the slide profile for one run:

```bash
AURA_PROFILE=slide4 ./run.sh "input.mp4" "outputs/input.json"
```

The short-video policy and a changed budget can affect organizer acceptance. Typical failures are printed to stderr. Check that the interpreter running `run.sh` has the required packages and that the weights are present and pass integrity checks.

| Exit | Meaning |
|---|---|
| 0 | Output written successfully |
| 1 | Unexpected internal error |
| 2 | Invalid command-line usage |
| 3 | Input video cannot be opened or processed |
| 4 | Model setup or inference failed |
| 5 | Pipeline or output validation failed |
| 6 | Output could not be written |
| 127 | Shell launcher could find no Python executable |

A failed run leaves an existing target intact. Check the exit code before using an output from a retried run.

## Submission

Rename this directory to your registered `TEAM_ID`. Install from the bundled dependencies and prepare the pinned weights on the machines that will run inference. Follow the organizer's packaging and redistribution rules for model artifacts.

```text
TEAM_ID/
  run.sh
  code/
  weights/
  requirements.txt
  outputs/
  README.md
```

Process every entry in the organizer's `manifest.csv` from its original footage. The guide requests 187 outputs, named `outputs/<video_id>.json`, with a consistent team ID. The package starts with an empty outputs directory. Organizer examples are test fixtures in the full project. They are illustrative and must stay out of submitted predictions.

For a collected directory, obtain the organizer's missing validator and run `python validate.py --dir outputs/` as described in the student guide. AURA checks its selected schema and vocabulary before every write. Check manifest IDs and duration agreement separately when preparing the submission. The student guide calls for a duration within 0.5 seconds of its manifest value.

The student guide describes six keys and the slide example shows four. Use the confirmed submission profile when available. The materials also disagree on the deadline and demo length. The general slides describe a working code repository, reproducible README, Docker files, a presentation, and a demo link as part of the event submission.

## Manifest batch

From the root of the full AURA project, run `python examples/run_manifest.py --help`. The default source list is the bundled 187-row CSV at `TEAM_ID/code/resources/manifest.csv`. The batch uses the same single-video CLIP launcher and reports missing or failed inputs alongside validated predictions. [Batch setup and reporting](../docs/DAY3_STUDENT_KIT.md)

## Model scope

The model performs zero-shot inference from sampled video frames. CLIP scores measure relative prompt fit. The action module makes coarse localizations and abstains when the window evidence fails its thresholds. The importance estimator combines explicit heuristics and model evidence. The official evaluation set and validator are separate from this package. The prototype has no official score.

The weights are a pinned MIT-licensed ONNX conversion of OpenAI CLIP, about 155 MB. Fetching and running use SHA-256 checks. [Pinned model revision](https://huggingface.co/Xenova/clip-vit-base-patch32/tree/6b7c523703ae26e39be4b03774966f8571c7f523) · [OpenAI CLIP license](https://github.com/openai/CLIP/blob/main/LICENSE)
