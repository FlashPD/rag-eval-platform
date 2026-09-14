# SciFact generation error analysis

## Scope

This analysis covers the completed 50-query, seed-42 SciFact generation run
[`ebd3a2dc`](../evals/runs/ebd3a2dc-e3db-4348-95a4-e38a10ee9d1d/report.md). The answer path used
`dense_bge_small`, the top 10 retrieved abstracts, prompt `scifact-v2`, and the pinned
`gpt-5.4-mini-2026-03-17` generator. The run was created from commit `833e876`; its report was
published at `7296402`.

The purpose is diagnosis, not another round of test-set prompt tuning. Proposed changes should be
developed on a separate slice and evaluated once on held-out claims.

## Executive findings

- All 50 generations completed with schema-valid output: 32 cited answers and 18 abstentions.
- Citation validity was 1.0000, so failures were semantic rather than citation-format failures.
- Label accuracy was 0.7800 (39/50) and three-class macro-F1 was 0.8000.
- Six of the 11 errors were `NOT_ENOUGH_INFO` claims labeled `SUPPORT`. Related evidence was often
  treated as entailment of a stronger, causal, or multi-clause claim.
- Three errors were conservative abstentions on `SUPPORT` claims. In all three cases the benchmark
  evidence document appeared in the top 10, but the claim depended on a qualifier, paraphrase, or
  short inference chain.
- Sentence-level rationale precision was the clearest weakness. Even among correctly classified
  claims, it averaged 0.322 for `SUPPORT` and 0.255 for `CONTRADICT`.
- A benchmark-relevant qrel document appeared in the generated context for 42/50 claims. Accuracy
  was 0.786 with it present and 0.750 without it; 9/11 label errors happened despite its presence.
  On this slice, label and evidence selection—not top-10 retrieval coverage—are the primary
  bottlenecks.

## Label confusion

Rows are benchmark labels and columns are generated labels.

| Gold label | `CONTRADICT` | `NOT_ENOUGH_INFO` | `SUPPORT` | Total |
|---|---:|---:|---:|---:|
| `CONTRADICT` | **9** | 0 | 1 | 10 |
| `NOT_ENOUGH_INFO` | 1 | **15** | 6 | 22 |
| `SUPPORT` | 0 | 3 | **15** | 18 |

| Label | Precision | Recall | F1 |
|---|---:|---:|---:|
| `CONTRADICT` | 0.900 | 0.900 | 0.900 |
| `NOT_ENOUGH_INFO` | 0.833 | 0.682 | 0.750 |
| `SUPPORT` | 0.682 | 0.833 | 0.750 |

The asymmetric error is operationally important: the model is more likely to turn insufficient
evidence into support than to miss support overall. A high citation-validity score does not prevent
this failure because a citation can be well formed while failing to entail the complete claim.

## Representative failures

| Claim ID | Gold → predicted | Observed behavior | Failure mode |
|---|---|---|---|
| `1207` | NEI → SUPPORT | A passage described polarized MIIB being downregulated while MIIA remains constitutive; the answer promoted that related trend into the claim's exact isoform “switch.” | Related evidence treated as full entailment |
| `1344` | NEI → SUPPORT | Separate p53 passages supported tumor suppression, senescence, and aging associations, but not the complete causal chain and shortened-lifespan claim as written. | Multi-clause evidence composition |
| `384` | NEI → CONTRADICT | A correlation between increasing NCD importance and rising SDI was used to infer the inverse prevalence claim for low-income settings. | Invalid inference from correlation/comparison |
| `431` | SUPPORT → NEI | The evidence document was retrieved at rank 7 and connected oxidative stress to MST1-mediated FOXO activation and neuronal death; the generator declined the ROS paraphrase and inference chain. | Conservative multi-hop abstention |
| `436` | SUPPORT → NEI | The rank-1 abstract stated that excess histones are degraded through a Rad53-dependent mechanism when replication slows or stops. The generator rejected the claim's “once DNA has been replicated” qualifier. | Temporal qualifier mismatch |
| `879` | CONTRADICT → SUPPORT | The claim and evidence combine negation, ribosome occupancy, translation, and functional protein production. The answer endorsed a nearby proposition without resolving the benchmark's polarity. | Negation and proposition-boundary error |

These examples also expose a benchmark constraint: a passage may look scientifically compatible
with a claim while the benchmark label remains `NOT_ENOUGH_INFO`. The system must optimize for
strict entailment under the benchmark definition, not topical plausibility.

## Rationale-selection failure

`scifact-v2` asks for zero-based supporting sentence indices “counted in the passage's displayed
text,” but the renderer supplies each abstract as an unnumbered text block. Sentence boundaries are
therefore implicit and ambiguous around abbreviations, parentheticals, and punctuation. The model
can produce a semantically appropriate citation while selecting indices that do not match the
benchmark's sentence segmentation.

| Correctly predicted class | Queries | Mean rationale precision |
|---|---:|---:|
| `CONTRADICT` | 9 | 0.255 |
| `NOT_ENOUGH_INFO` | 15 | 1.000* |
| `SUPPORT` | 15 | 0.322 |

\* Correct NEI predictions have empty gold and predicted rationales, which score 1.0 by definition;
this is not evidence-selection performance.

This metric currently measures precision only. It does not penalize a model that selects one valid
sentence while omitting other required evidence, so the observed 0.4526 aggregate should not be
interpreted as complete rationale quality.

## Recommended next experiment

1. Add a deterministic SciFact sentence splitter compatible with the benchmark metadata and render
   explicit markers such as `<sentence index="7">...</sentence>`.
2. Reject rationale indices that are out of bounds before persistence.
3. Change the generation sequence to evidence first: select exact sentence-level evidence, decide
   whether every material claim clause is entailed, and only then emit the label and answer.
4. Add development examples for negation, causal language, conjunctions, and qualifiers. Do not use
   the 50 claims in this report as few-shot examples.
5. Report per-class precision/recall/F1 and evidence-sentence recall alongside rationale precision.
6. Freeze the revised prompt and evaluate it once on a disjoint, deterministic SciFact sample.

Increasing model size is not the first recommendation. The current evidence points to input
representation and decision-procedure problems that a larger model could reproduce at higher cost.

## Claims this report does not make

- The 50-query sample is not a replacement for the full retrieval benchmark.
- Model-based faithfulness scores are descriptive; no human judge-calibration claim is made.
- The analysis does not establish that every apparent benchmark mismatch is an annotation error.
- No medical, scientific, or production-safety guarantee follows from these results.
