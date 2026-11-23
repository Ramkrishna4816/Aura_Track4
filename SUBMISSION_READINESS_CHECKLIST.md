# AURA Track 4 submission readiness

**ENGINEERING RELEASE COMPLETE — COMPETITION SUBMISSION NOT YET COMPLETE.** The production output directory contained zero registered predictions at the engineering audit. The student kit lists 187 originals. The local 185-video policy is conditional on written acceptance of both requested Scuba exclusions. [Evaluator submission status](docs/SUBMISSION_STATUS.md)

| Gate | Status | Evidence needed |
|---|---|---|
| Frozen launcher, runtime assets and local schema verification | COMPLETE | The engineering handoff verified 33 production files and the three pinned CLIP assets. The bundled manifest and taxonomy match the supplied student kit. |
| Exact registered team identifier | PENDING ORGANISER | Written case-sensitive ID for each `team_id` and for the package root name |
| Scuba exclusion decision | PENDING ORGANISER | Written decisions on `Scuba_KD74Ywuy9ng` and `Scuba_Um4kqB8bQBg`, with total mandatory coverage |
| Authoritative manifest and media sources | PENDING ORGANISER | Confirmed manifest and official sources for each required original, including exact FPVSum cuts |
| Complete authorized media | BLOCKED | Case-exact originals with trusted identity and checksum evidence. The six dashboard clips are outside the manifest. |
| Six-key schema and official validator | PENDING ORGANISER | Official validator and ruling on conflicting student-kit and slide examples |
| Four-second rule and 15% target | PENDING ORGANISER | Written precedence for short originals where four seconds exceeds 15% |
| Production predictions and official validation | BLOCKED | A complete fresh frozen batch with exact team ID, per-file hashes, strict local checks and official results |
| Final presentation and recording | PENDING TEAM | Approved PDF and PPTX, approved recording, and an access-tested hosted link |
| Demo length and footage permissions | PENDING ORGANISER | Written recording duration and guidance on display or redistribution of footage |
| Registration-gated form and deadline | PENDING ORGANISER | Operative submission form, deadline, time zone and required attachments |
| Competition archive and submission receipt | BLOCKED | Organizer-format archive, delivered form, and retained receipt |

## Questions for the organizer

Send these through the team's confirmed organizer channel.

1. What exact case-sensitive registered team identifier should we use for `team_id` and the team folder or archive name?
2. Can you confirm in writing whether `Scuba_KD74Ywuy9ng` and `Scuba_Um4kqB8bQBg` can be omitted? What is the required count, authoritative manifest and exact source for each video, including FPVSum cuts that differ from publisher renditions?
3. Could you provide the official validator and confirm which six-key schema applies? For a clip where the minimum four-second highlight exceeds 15% of its duration, which rule takes precedence?
4. What is the registration-gated submission form, operative deadline and time zone? What is the maximum demo video duration and what permissions must we have to display or redistribute original footage?

## Run only after confirmation

1. Acquire and verify the required originals. Hold any separately reserved data sealed until final inference is expressly authorized. Never use the six off-manifest demonstration videos as competition predictions.
2. Use the prepared frozen batch command on Linux or WSL. It requires the exact confirmation and a complete media provenance receipt. It leaves archived QA and the current production output folder untouched. [Confirmed batch runbook](docs/REPRODUCIBILITY.md#run-the-complete-confirmed-batch)
3. Run the official validator, verify exact output coverage and checksums, then assemble the organizer-format archive. The existing engineering source handoff is a reproducibility artifact.
4. Supply the approved presentation files and permitted recording, verify evaluator access to the GitHub branch and demo link, and file the submission. Preserve the organizer's receipt.
