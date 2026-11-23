# AURA demonstration

The six-video dashboard shows how AURA connects an overall activity label, time-localized verb–noun predictions and highlights to first-person source video. The two output panels compare frozen production stock with the opt-in factorized-refined development candidate. The action reference panel and the evaluation table use local development measurements.

## Watch

**Hosted recording · Pending team.** A team-approved recording URL is unavailable. The submitted recording needs permission for any included source footage and an access check from an evaluator account. [Recording link status](demo-link.txt)

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

## Recording access checklist

- [ ] Confirm the organizer’s duration limit and any required sections.
- [ ] Confirm permission to distribute any footage shown. If permission is unavailable, use an approved alternative or conceal the footage in the recording.
- [ ] Review the final recording for private information, unapproved footage and unsupported claims.
- [ ] Add the approved hosted recording URL here, in `demo-link.txt`, and in the repository README.
- [ ] From a logged-out browser or the evaluator’s intended account, verify that the recording opens and plays with the expected permissions.
