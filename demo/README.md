# AURA demonstration

The six-video dashboard shows how AURA connects an overall activity label, time-localized verb–noun predictions and highlights to first-person source video. The two output panels compare frozen production stock with the opt-in factorized-refined development candidate. The action reference panel and the evaluation table use local development measurements.

## Watch

**Hosted recording pending team approval.** The dashboard can be reproduced locally using the engineering handoff and authorised originals. An approved recording link will appear here after the team verifies evaluator access and any required footage permissions.

## Run the dashboard

Use the Python 3.12 environment from the reproduction guide. Restore the six-video benchmark, public reference subset and 12 saved model JSONs at their original `evaluation/` paths from the local engineering handoff. Use the licensed original videos obtained through an authorized source. [Development dashboard setup](../docs/DEVELOPMENT_DASHBOARD.md) · [Reproduction guide](../docs/REPRODUCIBILITY.md)

```powershell
$mediaRoot = Read-Host 'Path to the authorized EPIC-KITCHENS directory'
& .\.venv\Scripts\python.exe -B examples/make_multi_video_dashboard.py --media-root $mediaRoot --serve --open
```

Keep the terminal running while using the dashboard. Choose a clip, use a timeline segment to seek, and select **Play selections** to play both excerpts. **Actual output JSON** opens the saved prediction for either arm.

- `P06_02` shows a better-localized refined `open dishwasher` match and a separate false positive.
- `P09_04` shows three highlight intervals and cases where neither arm matched a reference action.
- `P14_03` shows how large frame changes can coincide with low activity relevance.

The screenshots in the [project README](../README.md) were captured from the dashboard. Original video pixels and detailed reference overlays were omitted from the repository copies. The displayed model outputs and local metrics come from the saved development run.
