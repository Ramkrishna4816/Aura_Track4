# AURA presentation and demo

Use the [release guide](SUBMISSION_RELEASE_GUIDE.md) for installation, submission inference, JSON rules, and packaging. The demo shows the released first-person video workflow. Record an authorized clip or use the synthetic generator for a repeatable software check.

## Presentation outline

Use the organizer's deck structure to tell the story in six short sections.

| Section | Content |
| --- | --- |
| Problem | Reviewing a first-person recording takes time when the reviewer needs to find a specific step or object interaction. |
| Solution | AURA returns a compact timeline with an activity label, any detected verb–noun actions, and highlight intervals. A reviewer can seek to those intervals in the original MP4. |
| Architecture | Show OpenCV sampling, the pinned CLIP CPU encoder, two-second joint action windows, and the evidence-based highlight planner. |
| Output | Show a generated six-key JSON beside the source playback. Point to a timestamp that visibly matches the demonstrated interval. |
| Evidence | State which demonstration input was used. Explain that the independent audit verified archived aggregate metrics and production hashes. Describe the limited action vocabulary, uncalibrated scores, and local scope of the measurements. |
| Demo and reproducibility | Include the verified shared repository and recording links once available. Keep the commands in the recorded README and credit the model and media. |

The supplied general rules describe a PPT or PDF named `CollegeName_TeamName` and a YouTube or Drive demo link. The organizer slides disagree on demo length and submission timing. A recording under three minutes fits both documented durations. Use the team's actual college name, registered name, final form, and confirmed deadline. [Current submission status](SUBMISSION_STATUS.md)

## Demo and recording procedure

1. Put a short, authorized first-person MP4 in a fresh demo directory. Choose a clip you can show publicly if the recording will be shared. Use an off-manifest stem such as `demo-input` and keep the demo directory separate from submitted predictions.
2. Run the frozen setup in the release guide, then launch one inference using the commands below. Use `python -m json.tool` to display the actual output. The manifest validator is for submission IDs and does not apply to an off-manifest demo clip.
3. In the recording, show the problem and input, run the command, point out `label`, `actions` and `highlights`, then seek to a selected highlight in the original video. If inference abstains, show the empty action list and explain how frame evidence still supports highlights.
4. Use the last few seconds to state the limitations and show where to reproduce the run. Inspect the video and terminal capture for private files, identifiers, or credentials before sharing.

On Windows use the same environment and model assets as the [PowerShell setup](../README.md#run-one-authorized-original). A shell label of `demo` marks a local demonstration artifact.

```powershell
$python = '.\.venv\Scripts\python.exe'
$env:AURA_PROFILE = 'readme6'
$env:AURA_TEAM_ID = 'demo'
$env:AURA_WEIGHTS_DIR = (Resolve-Path TEAM_ID/weights).Path
$env:AURA_SAMPLE_FPS = '2'
$env:AURA_ACTION_WINDOW_SECONDS = '2'
$env:AURA_BUDGET_RATIO = '0.15'
$env:AURA_MIN_HIGHLIGHT_SECONDS = '1'
$env:AURA_HIGHLIGHT_POLICY = 'minimum'
& $python TEAM_ID/code/run_aura.py 'runs/demo/demo-input.mp4' 'runs/demo/demo-input.json'
if ($LASTEXITCODE -ne 0) { throw 'Demo inference failed' }
& $python -m json.tool 'runs/demo/demo-input.json'
```

For a synthetic smoke check use the following command first, then pass `runs/demo/synthetic.mp4` and `runs/demo/synthetic.json` to the demo command. The synthetic file contains a moving shape and scene changes. Use it to show that decoding, inference, highlight generation, and JSON writing run end to end.

```powershell
& $python examples/make_smoke_video.py 'runs/demo/synthetic.mp4'
```

Suggested timing is 20 seconds for the problem, 30 seconds for the pipeline, 80 seconds for the run and timeline, and 30 seconds for evidence and limitations. The workspace retains earlier real-media demonstration evidence under `evaluation/`.
