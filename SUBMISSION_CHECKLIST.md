# Track 4 submission checklist

The local source handoff prepares the repository files and pinned runtime assets for release. A registered team submission remains pending.

Use the [current submission status](docs/SUBMISSION_STATUS.md) and [organizer confirmation checklist](SUBMISSION_READINESS_CHECKLIST.md) for the evaluator portal and final preparation.

## Completed

- [x] Matched the bundled manifest and taxonomy to the student kit. Retained the six-key JSON profile and canonical taxonomy, including `ski`.
- [x] Preserved the frozen launcher, inference code, configuration, prompt bank, Docker files and three pinned CLIP assets.
- [x] Prepared the local validator, inference commands, source handoff workflow, and demo run sheet.
- [x] Revalidated the 11 archived Day 3 QA outputs with their recorded QA identifier. Strict validation identified the missing outputs.
- [x] Recorded Git provenance as an archive receipt. The active export has no verifiable HEAD.

## Pending

- [ ] Set `AURA_TEAM_ID` from the exact registration receipt. Use the same identifier for every prediction and the organizer package root.
- [ ] Confirm the final form, deadline and output specification with the organizer. The slide editions disagree on dates and show different schema examples. The student kit specifies six keys.
- [ ] Confirm the two Scuba exceptions against the organizer's 187-video kit requirement. The local validator and batch runner target the requested 185 after exclusions.
- [ ] Obtain eligible organizer-authorized originals and confirm media identity before inference. Use a fresh output directory and run strict validation before assembling a candidate.
- [ ] Complete `CollegeName_TeamName` PPT/PDF and a YouTube or Drive demo with a three-minute target. Use the existing recording procedure. [Presentation and demo run sheet](docs/FINAL_SUBMISSION.md)

## Blocked

- [ ] **Registered predictions and organizer ZIP.** The registration ID is missing and the current production output directory has zero predictions. The available QA JSONs carry historical identifiers.
- [ ] **Complete coverage.** The remaining originals and organizer-approved input set are unresolved. Nine verified EPIC originals remain reserved. Three downloaded FPVSum renditions lack organizer media alignment evidence.
- [ ] **Access for evaluators.** The engineering branch and tag were published. Confirm that the evaluator account can open the repository and the release links before filing the submission.
- [ ] **Official validation and upload.** The kit omits the referenced `validate.py`. The registration-gated final form URL, completed deck and demo link are missing.

The local source handoff contains the repository materials, verified runtime weights and a per-file SHA-256 receipt. It contains zero predictions and has no registered team identity. [Install, run and validate](docs/SUBMISSION_RELEASE_GUIDE.md)
