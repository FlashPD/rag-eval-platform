# Model and evaluation card

## System summary

`ragops` is an evaluation and observability system for retrieval-augmented generation. It compares
retrieval strategies, generates schema-constrained cited answers, applies deterministic and
model-based metrics, and publishes reproducible reports with model, prompt, configuration, index,
and source-commit provenance.

This card describes the checked-in portfolio configuration, not every model that the provider or
framework could support.

## Configured components

| Role | Model | Execution | Why it is used |
|---|---|---|---|
| Dense embedding | `BAAI/bge-small-en-v1.5` | Local sentence-transformers; CPU or Apple MPS | A compact 384-dimensional encoder with a practical local quality/latency tradeoff |
| Reranking | `cross-encoder/ms-marco-MiniLM-L-6-v2` | Local sentence-transformers; CPU or Apple MPS | A conventional cross-encoder baseline for measuring whether added ranking cost improves quality |
| Answer generation | `gpt-5.4-mini-2026-03-17` | OpenAI Responses API; low reasoning; 2,048 output-token cap | Structured-output support and a lower-cost generation profile |
| Primary judge | `gpt-5.4-2026-03-05` | OpenAI Responses API; medium reasoning; 4,096-token cap | A stronger, separately configured faithfulness and relevance evaluator |
| Secondary judge | `gpt-5.4-mini-2026-03-17` | OpenAI Responses API; medium reasoning; 2,048-token cap | A lower-cost independent check for judge sensitivity |

Exact configuration lives in [`config/models.yaml`](../config/models.yaml); token prices used by
reports live in [`config/pricing.yaml`](../config/pricing.yaml). Model and parameter configuration
is content-hashed, so changing a model, effort, or token limit changes cache and comparison
provenance.

## Intended use

- Offline or CI evaluation of BM25, dense, hybrid, and reranked retrieval.
- Reproducible comparison of retrieval quality, latency, and statistically paired differences.
- Development-time evaluation of cited answers, abstention, claim labels, evidence rationales,
  faithfulness, relevance, and API cost.
- Demonstrating production-oriented AI evaluation patterns without requiring a persistent cloud
  deployment.

## Out-of-scope use

- Direct medical, financial, legal, or scientific decision-making.
- Treating an LLM judge score as ground truth or as a substitute for expert review.
- Using generated SciFact labels as new scientific evidence.
- Production workloads containing confidential or regulated text without a separate privacy,
  retention, access-control, and provider review.
- Claiming cloud reliability from infrastructure code that has not been deployed and exercised.

## Evaluation evidence

### Retrieval

The full test splits of three checksum-pinned BEIR datasets were evaluated with four retrieval
variants. The best nDCG@10 point estimate depends on domain:

| Dataset | Queries | Best variant | nDCG@10 |
|---|---:|---|---:|
| SciFact | 300 | Dense | 0.7200 |
| NFCorpus | 323 | Hybrid + rerank | 0.3591 |
| FiQA-2018 | 648 | Dense | 0.3848 |

The README and linked run artifacts contain confidence intervals and paired-bootstrap comparisons;
point-estimate winners are not automatically treated as significant.

### Generated answers

The portfolio generation report evaluates 50 deterministic seed-42 SciFact claims using dense
top-10 context:

| Metric | Result |
|---|---:|
| Completed structured generations | 50/50 |
| Citation validity | 1.0000 |
| Abstention correctness | 0.6800 |
| Label accuracy | 0.7800 |
| Three-class macro-F1 | 0.8000 |
| Rationale precision | 0.4526 |
| Primary judge faithfulness | 0.9034 |
| Secondary judge faithfulness | 0.9600 |

See the [complete run report](../evals/runs/ebd3a2dc-e3db-4348-95a4-e38a10ee9d1d/report.md) and
[generation error analysis](generation_error_analysis.md). The error analysis is part of the model
evidence: strong format validity did not imply equally strong entailment or sentence-level evidence
selection.

## Cost profile

The 50 unique generations and 100 unique judge verdicts have a reconstructed cold-equivalent cost
of $1.4137, or $0.0283 per evaluated query, under the checked-in pricing table:

| Component | Cost |
|---|---:|
| Generator | $0.2246 |
| Primary judge | $0.9012 |
| Secondary judge | $0.2879 |

Run reports record incremental cost: immutable cache hits have zero new token spend. The default
GitHub portfolio workflow is retrieval-only and makes no OpenAI calls.

## Known limitations

- Generation evidence covers one 50-query SciFact sample; it is not cross-domain validation.
- The sample was used for diagnosis, so future prompt changes must be evaluated on a disjoint slice
  to avoid test-set overfitting.
- Human judge calibration is deferred. Primary and secondary scores are descriptive model-based
  measurements, not validated estimates of human preference or factuality.
- Rationale indices are selected from unnumbered abstract text. Ambiguous sentence segmentation is
  a likely contributor to low sentence-level precision.
- SciFact labels reward strict benchmark entailment. Topically related passages can still be
  insufficient for a causal, conjunctive, temporal, or otherwise stronger claim.
- Retrieved top-10 context averages 0.102 precision on the generation slice, so the generator must
  reject substantial distractor evidence.
- Provider latency was not persisted in the archived answer report. Retrieval stage latency is
  measured separately and should not be presented as end-to-end answer latency.
- The cross-encoder adds substantial CPU latency and did not produce a statistically significant
  SciFact improvement over the cheaper dense or hybrid alternatives.

## Safety and data handling

- Queries and passages are marked as untrusted data and XML escaped before prompting.
- Provider responses use strict schemas, deterministic citation validation, and one bounded repair
  attempt for incomplete schema output.
- OpenAI requests set `store=False`; the claim and retrieved passages are still sent to the
  configured external provider for generation or judging.
- API keys are loaded from environment-backed secret settings and are not written into reports.
- Generation and judge caches retain answers, contexts, verdicts, token usage, and provider request
  identifiers in PostgreSQL. Only public benchmark data should be used in the portfolio setup.
- Production API-key authentication fails closed when no key hashes are configured; local
  development may run without application-level API authentication.

## Reproducibility

Each evaluation run records the dataset and split, deterministic sample seed, variant hashes,
content-derived index fingerprints, model configuration hashes, prompt versions, source commit,
token usage, and cached-call state. Markdown and JSON reports are committed together. Dataset
sources, checksums, terms, and observed corpus quirks are documented in the
[dataset card](data_card.md).

## Review triggers

Re-run evaluation and revise this card when any of the following changes:

- embedding, reranker, generator, or judge model;
- prompt version, response schema, reasoning effort, or token limit;
- chunking, sentence segmentation, retrieval depth, fusion, or reranking behavior;
- dataset archive or checksum;
- metric definition, judge rubric, pricing table, or regression threshold.
