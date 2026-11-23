# Reproduce AURA

## Set up the frozen runtime

Use Python 3.12. From the repository root on Linux or WSL, create a fresh environment, install the pinned runtime, and acquire the three checksum-verified model assets. Inference runs on CPU.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r TEAM_ID/requirements.txt
python -m pip check
python -B TEAM_ID/code/fetch_weights.py --weights-dir "$PWD/TEAM_ID/weights"
```

The local engineering source handoff includes the same three verified assets. The GitHub repository supplies a pinned download script and hashes. [Model manifest](MODEL_WEIGHTS.json) · [Model license notice](../licenses/OpenAI-CLIP-MIT.txt)

## Run one authorized original

For an output intended for competition use, set `AURA_TEAM_ID` to the exact entry in written organizer confirmation. Keep the organizer's case-exact video stem and choose a fresh output filename. Set the frozen runtime options explicitly in shells that may have experimentation settings.

```bash
: "${AURA_TEAM_ID:?Export the confirmed registered team ID}"
: "${VIDEO:?Export the path to the authorized original MP4}"
: "${OUTPUT:?Export a fresh path for the JSON output}"
AURA_PROFILE=readme6 AURA_TEAM_ID="$AURA_TEAM_ID" AURA_WEIGHTS_DIR="$PWD/TEAM_ID/weights" \
  AURA_SAMPLE_FPS=2 AURA_ACTION_WINDOW_SECONDS=2 AURA_BUDGET_RATIO=0.15 \
  AURA_MIN_HIGHLIGHT_SECONDS=1 AURA_HIGHLIGHT_POLICY=minimum PYTHON="$PWD/.venv/bin/python" \
  ./TEAM_ID/run.sh "$VIDEO" "$OUTPUT"
```

On Windows, `python TEAM_ID/code/run_aura.py <input_video.mp4> <output.json>` calls the same Python entry point. Set the same `AURA_` environment variables as above. The launcher and its defaults remain frozen. [Output contract](SUBMISSION_RELEASE_GUIDE.md#output-contract) · [Production source](../TEAM_ID/run.sh)

## Open the development dashboard

Use the local engineering source handoff with its six-video benchmark, approved public reference subset and saved stock/refined JSONs. Obtain authorized originals separately. This checkout does not include those data files. See the dashboard guide for its expected directory structure and browser test commands. [Dashboard setup](DEVELOPMENT_DASHBOARD.md) · [Evaluation](EVALUATION_REPORT.md)

## Run the complete confirmed batch

Wait for written organizer confirmation of the registered team ID, authoritative manifest and source access, Scuba exclusion decision, exact six-key profile and highlight rules, and official validator. The prepared command checks that the approved profile matches the frozen `readme6` profile. If the organizer requires a different profile or a different ID set, stop and reconcile the contract before inference.

Create two private records outside the tracked source tree. Keep actual organizer correspondence and all media paths out of Git. The `--approval` JSON needs these fields. Populate every value from written evidence.

| Field | Source |
|---|---|
| `team_id` | Exact case-sensitive registered identifier |
| `confirmation_reference` | Pointer to the organizer's written confirmation of identifier, manifest, media, scope, schema and highlight rules |
| `manifest_sha256` | SHA-256 of the authorized manifest file |
| `official_validator_sha256` | SHA-256 of the supplied official validation file |
| `excluded_video_ids` | `[]` for 187, or both exact Scuba IDs after written approval for 185 |
| `validation_profile` | `readme6` after the six-key contract is confirmed |

Record the authorized originals in a UTF-8 CSV with header `video_id,sha256,source_reference`. Include one row per selected video, a trusted lowercase 64-character SHA-256 for its exact original bytes, and a reference identifying how that approved source was established. Stage the verified media in flat read-only directories with exact manifest stems. The wrapper checks bytes before and after the frozen runner. Hold all media and records stable during the run.

```bash
: "${AURA_TEAM_ID:?Export the confirmed registered team ID}"
: "${APPROVAL:?Export the path to the private approval record}"
: "${AUTHORIZED_MANIFEST:?Export the path to the authorized manifest}"
: "${PROVENANCE:?Export the path to the private media provenance CSV}"
: "${OFFICIAL_VALIDATOR:?Export the path to the official validator file}"
: "${EPIC_ORIGINALS:?Export the path to the verified EPIC originals}"
: "${FPVSUM_ORIGINALS:?Export the path to the verified FPVSum originals}"
: "${RUN_DIR:?Export a path to a new run directory}"
python -B examples/prepare_confirmed_submission.py \
  --team-id "$AURA_TEAM_ID" --approval "$APPROVAL" \
  --manifest "$AUTHORIZED_MANIFEST" --provenance "$PROVENANCE" \
  --official-validator "$OFFICIAL_VALIDATOR" --weights "$PWD/TEAM_ID/weights" \
  --media-dir "$EPIC_ORIGINALS" --media-dir "$FPVSUM_ORIGINALS" --run-dir "$RUN_DIR"
```

The wrapper preserves the authorized and selected manifests, `input-provenance.json`, `inference/processing-report.json`, per-video launcher logs, `local-validation.json` and `coverage.json`. Local completion requires the exact approved output count, verified run sources and strict local schema validation. `coverage.json` records each generated output hash. A failed preflight stops before launching inference. The wrapper checks the official validator file's identity and records official validation as pending.

Run the organizer validator using the exact instructions supplied with it. Archive the reports and check that the files you package match the recorded output hashes. Use the registered folder name only after checking the submitted archive requirements. The legacy ZIP builder and standalone validator default to the two local exclusions. Use the new wrapper for full 187-row local validation and follow the organizer's archive instructions for that scope. [Prepared wrapper](../examples/prepare_confirmed_submission.py) · [Organizer gates](../SUBMISSION_READINESS_CHECKLIST.md)

## Inspect verification evidence

The engineering run recorded 442 passing Python tests and 373 passing subtests, plus 19 platform or optional-dependency skips. Seven rescue-demo and five multi-video browser scenarios passed. These checks cover software behavior and asset integrity. [Recorded verification and development metrics](EVALUATION_REPORT.md)
