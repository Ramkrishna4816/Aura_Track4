# Evaluator guide

Start with the [repository README](../README.md) for the project and results. The [dashboard and recording guide](../demo/README.md) explains how to replay the development examples. The [release tag](https://github.com/Ramkrishna4816/Aura_Track4/tree/aura-track4-engineering-v1) identifies the existing engineering baseline.

| Hackathon checkbox | Repository location | Status | Evidence |
|---|---|---|---|
| Submission package | [Submission status](SUBMISSION_STATUS.md), [`TEAM_ID/`](../TEAM_ID/) | **BLOCKED** | Engineering source handoff verified. The organiser-format submission has 0 registered outputs and unresolved scope, media, team ID and official validation. |
| Source Code | [`TEAM_ID/code/`](../TEAM_ID/code/), [launcher](../TEAM_ID/run.sh), [build receipt](../SOURCE_HANDOFF.json) | **COMPLETE** | Frozen source and pinned model fetcher are available in the engineering branch and release checkout. Confirm evaluator access before submitting. |
| Presentation | [`presentation/`](../presentation/) | **PENDING TEAM** | Team approval and public release pending. |
| Video | [`demo/README.md`](../demo/README.md) | **PENDING TEAM** | The dashboard setup is available. Public recording approval and evaluator access are pending. |
| AI Disclosure | [`docs/AI_DISCLOSURE.md`](AI_DISCLOSURE.md) | **PENDING TEAM** | Evidenced Codex use documented. Team-specific authorship, review and verification declarations await confirmation. |
| README | [`README.md`](../README.md) | **COMPLETE** | The evaluator portal is present in this checkout. Remote publication and external viewer access are separate checks. |
| APK/SDK (if any) | [Runtime and interfaces](ARCHITECTURE.md#runtime-and-interfaces) | **NOT APPLICABLE** | AURA is a Python command-line workflow with a Docker runtime and a local browser dashboard. This release contains no mobile app or SDK. |
| Other | [Architecture](ARCHITECTURE.md), [evaluation](EVALUATION_REPORT.md), [reproducibility](REPRODUCIBILITY.md), [`tests/`](../tests/) | **COMPLETE** | Production diagram, study scope, engineering evidence and verification commands. |

**Engineering source handoff ≠ competition submission package.** The branch and tag contain reproducible engineering source. The local handoff additionally contains the pinned model assets and authorised development artifacts. The registered package gate depends on written organiser requirements, complete exact-source inference outputs, and official validation. [Full gate](SUBMISSION_STATUS.md)
