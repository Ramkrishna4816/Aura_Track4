# Local development evaluation

The dashboard compares the frozen stock configuration with the opt-in factorized-refined candidate. The comparison uses saved predictions from six public EPIC-KITCHENS development clips, with 44 annotated actions across three participants. All clips represent cooking, and their IDs sit outside the competition manifest. No reserved competition material was used in the comparison. [Dashboard setup](../demo/README.md)

| Metric | Frozen stock | Factorized-refined, opt-in |
|---|---:|---:|
| Mean local action mAP across tIoU 0.10–0.50 | 1.081% | 1.622% |
| Matched reference actions at tIoU 0.30 | 0/44 | 1/44 |
| Recall at tIoU 0.30 | 0.00% | 2.27% |
| Precision at tIoU 0.30 | 0.00% | 50.00% |
| False-positive detections at tIoU 0.30 | 2 | 1 |
| Distinct annotated pairs covered by highlights | 8/41 | 8/41 |
| Clips with zero action detections | 4/6 | 5/6 |

Local matching uses confidence-ranked, one-to-one assignments with exact verb and noun keys and a temporal intersection-over-union threshold. The highlight proxy counts a distinct annotated pair when highlights cover at least half of one annotated instance. The study did not measure human highlight F1.

| Development clip | Reference actions | Stock match / false positive / missed | Refined match / false positive / missed |
|---|---:|---:|---:|
| P06_02 | 6 | 0 / 1 / 6 | 1 / 1 / 5 |
| P06_08 | 6 | 0 / 0 / 6 | 0 / 0 / 6 |
| P09_01 | 3 | 0 / 0 / 3 | 0 / 0 / 3 |
| P09_04 | 19 | 0 / 1 / 19 | 0 / 0 / 19 |
| P14_02 | 8 | 0 / 0 / 8 | 0 / 0 / 8 |
| P14_03 | 2 | 0 / 0 / 2 | 0 / 0 / 2 |

Five videos had no refined detections. The single improved match on P06_02 demonstrates a local interval change, with limited evidence of generalisation. P09_04 shows multiple highlight intervals despite no correct action match, and P14_03 shows why camera motion matters to highlight ranking. Both variants classified all six clips as cooking, which was the only represented activity.

The candidate stays opt-in, and the experimental two-frame support rule remains outside production. The local evaluation is development evidence. The restricted competition evaluation and an official score remain unavailable. Engineering tests measure executable behaviour and integrity separately from model accuracy. [Reproduction and test evidence](REPRODUCIBILITY.md) · [Submission status](SUBMISSION_STATUS.md)
