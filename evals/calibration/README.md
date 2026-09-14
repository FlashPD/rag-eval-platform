# Judge calibration labels

`labels.jsonl` is intentionally not synthesized by the model under evaluation. Create roughly 100
rows sampled across SciFact, NFCorpus, and FiQA, then have a human annotator fill
`human_faithful` and `human_relevant`. Each row must match the `CalibrationLabel` contract and
include the question, answer, abstention flag, citations, exact supplied passages, annotator
identifier, and a stable ID. Do not include provider-generated labels in these two human fields.

The calibration command validates unique IDs and exact judge coverage before reporting Cohen's
kappa independently for faithfulness and relevance. Do not publish judge scores until a reviewed
`labels.jsonl` and its agreement report are committed.

Run both configured judges after the labels are reviewed:

```bash
ragops eval calibrate \
  --labels evals/calibration/labels.jsonl \
  --judge-profiles default,secondary
```
