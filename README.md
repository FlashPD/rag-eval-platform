# RAG Evaluation & Observability Platform

`ragops` makes retrieval quality measurable, reproducible, and safe to change. It indexes public
information-retrieval benchmarks, serves several swappable retrieval strategies behind one API, and
scores them with deterministic metrics, confidence intervals, and a regression gate that fails a
build when quality drops.

The product is the measurement, not the search.

## Results

All test queries in three BEIR domains, using `BAAI/bge-small-en-v1.5` embeddings and
`cross-encoder/ms-marco-MiniLM-L-6-v2` reranking on CPU. Values are nDCG@10; each linked report
contains nDCG@10, Recall@10, Recall@100, MRR@10, 95% intervals, stage latency, and all 24 paired
variant comparisons.

| Dataset | Queries / documents | BM25 | Dense | Hybrid | Hybrid + rerank | Full report |
|---|---:|---:|---:|---:|---:|---|
| SciFact | 300 / 5,183 | 0.6617 | **0.7200** | 0.7085 | 0.6934 | [`447d6235`](evals/runs/447d6235-3773-44a3-bc4d-bbf96df2c159/report.md) |
| NFCorpus | 323 / 3,633 | 0.3064 | 0.3375 | 0.3444 | **0.3591** | [`2d9f6192`](evals/runs/2d9f6192-1704-4b4a-908d-3508b1fa04bd/report.md) |
| FiQA-2018 | 648 / 57,638 | 0.2326 | **0.3848** | 0.3436 | 0.3731 | [`a0611a31`](evals/runs/a0611a31-bd3a-4bb5-976c-c3a885230c93/report.md) |

The point-estimate winner changes with the domain: dense wins SciFact and FiQA, while reranked
hybrid wins NFCorpus. The paired results sharpen that observation. On NFCorpus, reranked hybrid
beats dense by 0.0216 nDCG@10 with a 95% interval of [0.0044, 0.0392]. On SciFact and FiQA, the
dense-versus-reranked intervals include zero, so their apparent dense advantage is not significant.
Plain hybrid never wins nDCG@10, although it ties reranked hybrid on Recall@100 by construction.

### SciFact detail

BEIR SciFact, **all 300 test queries**, `BAAI/bge-small-en-v1.5` embeddings and
`cross-encoder/ms-marco-MiniLM-L-6-v2` reranking on CPU. Run
`447d6235-3773-44a3-bc4d-bbf96df2c159` at commit `3e2cc66`; the full report, including every
confidence interval and all 24 pairwise comparisons, is archived at
[`evals/runs/447d6235-3773-44a3-bc4d-bbf96df2c159/report.md`](evals/runs/447d6235-3773-44a3-bc4d-bbf96df2c159/report.md).

| Variant | nDCG@10 | Recall@10 | Recall@100 | MRR@10 |
|---|---:|---:|---:|---:|
| `bm25` | 0.6617 | 0.7739 | 0.8759 | 0.6312 |
| `dense_bge_small` | **0.7200** | **0.8452** | 0.9533 | **0.6845** |
| `hybrid_rrf` | 0.7085 | 0.8319 | **0.9650** | 0.6736 |
| `hybrid_rrf_rerank` | 0.6934 | 0.8222 | **0.9650** | 0.6619 |

Stage latency, P50 and P95 in milliseconds over the same run:

| Variant | Sparse | Embed | Dense | Fuse | Rerank | Hydrate |
|---|---:|---:|---:|---:|---:|---:|
| `bm25` | 2.2 / 2.8 | — | — | — | — | 7.4 / 8.2 |
| `dense_bge_small` | — | 16.4 / 20.0 | 23.2 / 25.0 | — | — | 5.9 / 7.0 |
| `hybrid_rrf` | 1.8 / 2.1 | 15.8 / 19.3 | 22.4 / 24.8 | 0.4 / 0.5 | — | 6.0 / 6.9 |
| `hybrid_rrf_rerank` | 1.7 / 1.9 | 16.2 / 18.7 | 20.6 / 24.1 | 0.4 / 0.5 | 1140.6 / 1296.6 | 8.7 / 10.0 |

Reproduce both tables from an ingested corpus:

```bash
.venv/bin/ragops eval run \
  --dataset scifact \
  --variants bm25,dense_bge_small,hybrid_rrf,hybrid_rrf_rerank \
  --seed 42
.venv/bin/ragops eval report <run_id>
```

### Which differences are real

Point estimates alone cannot say whether one variant beats another. `eval report` runs a paired
bootstrap over queries for every variant pair and metric: it resamples queries and reads both
variants at the same query indices, so the interval measures the per-query gap rather than the much
wider spread of two independently estimated means. A difference counts as significant only when its
95% interval excludes zero.

| Comparison | Metric | A - B | 95% CI | Significant |
|---|---|---:|---:|---|
| `bm25` vs `dense_bge_small` | nDCG@10 | -0.0583 | [-0.0980, -0.0171] | yes |
| `bm25` vs `dense_bge_small` | MRR@10 | -0.0532 | [-0.0969, -0.0100] | yes |
| `bm25` vs `hybrid_rrf` | nDCG@10 | -0.0468 | [-0.0696, -0.0245] | yes |
| `bm25` vs `hybrid_rrf_rerank` | nDCG@10 | -0.0317 | [-0.0649, +0.0013] | no |
| `dense_bge_small` vs `hybrid_rrf` | nDCG@10 | +0.0115 | [-0.0167, +0.0391] | no |
| `dense_bge_small` vs `hybrid_rrf_rerank` | nDCG@10 | +0.0266 | [-0.0024, +0.0578] | no |
| `hybrid_rrf` vs `hybrid_rrf_rerank` | nDCG@10 | +0.0151 | [-0.0142, +0.0422] | no |
| `hybrid_rrf` vs `hybrid_rrf_rerank` | Recall@100 | +0.0000 | [+0.0000, +0.0000] | no |

- **Dense and hybrid retrieval both beat BM25, on every metric.** Each of the eight
  `bm25`-versus-`dense_bge_small` and `bm25`-versus-`hybrid_rrf` comparisons is significant. This is
  the expected direction for a scientific-claim benchmark where lexical overlap between a claim and
  its abstract is weak.
- **Cross-encoder reranking does not pay for itself on this benchmark.** It costs about 1.14 s of
  P50 latency per query on CPU — roughly fifty times the entire dense pipeline — and every
  comparison against `hybrid_rrf` is non-significant. Worse, the point estimates favour plain
  `hybrid_rrf` on three of four metrics, and `hybrid_rrf_rerank` is the only variant that fails to
  significantly beat BM25 on nDCG@10. On this corpus the reranker is latency spent for no measurable
  quality.
- **Among dense, hybrid, and reranked hybrid there is no measurable winner.** Every pairwise
  comparison between those three has an interval spanning zero, even at 300 queries. Hybrid buys the
  best deep recall (0.9650 versus 0.9533) and dense holds the best top-10 point estimates, but the
  data does not support declaring either better.
- **Reranking cannot change deep recall, and the numbers confirm it.** `hybrid_rrf` and
  `hybrid_rrf_rerank` differ on Recall@100 by exactly zero with a zero-width interval, because
  reranking reorders the candidate window rather than truncating the result list, leaving both
  variants retrieving the same pool to the same depth.

### Why the full test set, not a sample

An earlier 50-query sample of this same corpus put BM25 at 0.5671 nDCG@10 and `hybrid_rrf` at
0.6248, and ranked `hybrid_rrf_rerank` above `hybrid_rrf`. The full 300-query run puts BM25 at
0.6617 and reverses that ordering. The sample was not wrong, it was small: it happened to draw
harder queries, and at that width almost nothing separated the variants.

This is why the headline numbers come from the full test set, and why the 50-query slice used by the
pull-request gate is treated as a fast regression canary on a fixed set of queries rather than as an
estimate of benchmark quality. Retrieval is deterministic, so that slice detects a regression
exactly; it just should not be quoted as a headline result.

## What is implemented

- A Python 3.13 application scaffold with a root virtual environment, FastAPI, CLI tooling, pinned
  development dependencies, Ruff, strict mypy, pytest, pre-commit, and CI.
- Strict Pydantic contracts and validated YAML configuration for datasets, retrieval variants,
  models, pricing, evaluation thresholds, metrics, gates, judges, and jobs. Configuration is
  content-hashed so runs and index artifacts can be reproduced.
- An async SQLAlchemy and PostgreSQL persistence layer with Alembic migrations, fixed-size
  `vector(384)` embeddings, a cosine HNSW index, repositories, and UTC-normalized timestamps.
- A durable PostgreSQL job queue with idempotent submission, `FOR UPDATE SKIP LOCKED` claims,
  leases, heartbeats, retries, cancellation, and stale-worker protection.
- A resumable BEIR ingestion pipeline for the checked-in fixture and checksum-pinned SciFact,
  NFCorpus, and FiQA archives. It securely downloads and validates archives, loads documents,
  queries, and qrels in committed batches, creates content-addressed BM25 artifacts, and persists
  length-bucketed sentence-transformer embeddings with recoverable index-build progress.
- Sparse BM25, dense pgvector, reciprocal-rank-fusion hybrid, and cross-encoder reranked retrieval
  pipelines. Search results preserve stage scores, deterministic ranks, stage latencies,
  configuration hashes, and trace identifiers. Reranking reorders its candidate window instead of
  truncating the result list, so every variant retrieves to the same depth and deep metrics stay
  comparable.
- A `POST /v1/search` endpoint with validated request and response schemas, API error mapping, lazy
  model loading, OpenTelemetry spans, Prometheus request and retrieval-stage metrics, a `/metrics`
  endpoint, and health and readiness endpoints.
- Asynchronous evaluation submission: `POST /v1/evals` writes the run and its queue job in one
  transaction and returns immediately, `GET /v1/evals/{run_id}` reports progress, and a `ragops
  worker` process claims jobs, renews its lease while a run executes, retries failures, and shuts
  down gracefully on `SIGINT` or `SIGTERM`.
- Deterministic per-query retrieval metrics (nDCG@10, Recall@10, Recall@100, MRR@10) and a resumable
  evaluation runner with seeded query sampling, variant-hash validation, transactional result
  persistence, progress tracking, and cooperative cancellation.
- Evaluation aggregation with seeded bootstrap confidence intervals, paired-bootstrap significance
  testing between every variant pair, stage-level P50/P95 latency, and reproducible Markdown or JSON
  reports archived under `evals/runs/`.
- A regression gate that compares a completed run against a committed per-dataset baseline, refuses
  comparisons across different benchmarks, prints a per-metric diff, and distinguishes a quality
  regression from an unusable comparison by exit code.
- Portable index provenance on every run and baseline. Each variant records a content-derived
  fingerprint covering the corpus, embedding and HNSW configuration, and BM25 artifact. The gate
  rejects a changed index or variant configuration before comparing quality metrics, without
  depending on database-local UUIDs, and Markdown and JSON reports expose the fingerprints used.
- A CPU-first, non-root Docker image that builds natively on Apple Silicon and `amd64`, plus a
  Compose stack for pgvector, automatic Alembic migrations, the API, evaluation worker,
  OpenTelemetry Collector, Tempo, Prometheus, and Grafana. Langfuse v4 and its backing services are
  available through an optional higher-memory profile.
- Repository-provisioned Prometheus, Tempo, and Grafana configuration, including a service-health
  dashboard for request rate, HTTP P95 latency, and retrieval-stage P95 latency. Traces flow from
  the API through the OpenTelemetry Collector into Tempo.
- Pull-request regression jobs that start pgvector and gate both the checked-in fixture and a
  three-dataset matrix against committed baselines. The real-dataset jobs restore content-addressed
  PostgreSQL index snapshots when available, validate them through idempotent ingestion, run all
  four variants on the seed-42 50-query slices, and upload their reports. Cache misses build and
  save the checksum-pinned corpus, BM25 artifact, and embeddings before evaluation.
- Provider-neutral `Answerer` and `Generator` protocols with strict contracts for rendered prompts,
  structured cited answers, provider/model provenance, token usage, and deterministic citation
  validation. Invalid, duplicate, missing-inline, and abstention-inconsistent citations are
  reported explicitly instead of being repaired.
- A reviewed `answer-v1` system prompt and deterministic renderer that rank-orders contexts and
  escapes the question, identifiers, titles, and passage text into an explicitly untrusted XML
  block. Each rendered request has a content hash suitable for response-cache keys, and the prompt
  asset is included in the runtime image.
- A provider-neutral `CitedAnswerer` orchestrator that renders requests, calls a configured
  generator, validates citations, and classifies successful answers, evidence-based abstentions,
  citation errors, schema failures, refusals, provider failures, and timeouts. Responses retain the
  exact contexts, model and prompt provenance, provider request identifier, usage, cost, and trace.
- An immutable PostgreSQL generation cache keyed by provider, model parameters, prompt version,
  response schema, and rendered prompt content. A provider-neutral caching decorator reuses the
  structured output on unchanged requests, reports zero incremental token usage and cost, removes
  the stale provider request identifier, and never caches failures.
- An OpenAI Responses API adapter using pinned GPT-5.4 snapshots, strict structured outputs,
  configurable reasoning effort, explicit refusal/timeout/provider failure handling, one schema
  repair attempt, stable prompt-cache keys, cached-token accounting, and configuration-driven cost.
- `POST /v1/answer`, which retrieves a named dataset/variant, assigns stable local passage IDs,
  returns a validated cited answer with complete provenance, and can asynchronously sample live
  answers without adding judge latency to the request path.
- A resumable answer-evaluation path layered onto the retrieval runner. It deterministically samples
  generation queries and variants, resumes independently at retrieval, generation, and judging,
  and reports citation validity, context precision, abstention correctness, provider cost, primary
  and secondary judge faithfulness/relevance, plus SciFact three-way macro-F1 and rationale
  precision from the benchmark's original evidence metadata.
- Versioned, injection-resistant SciFact and judge prompts; a separately configured primary and
  secondary OpenAI judge; immutable judge-response caching; judge-model/prompt comparability checks
  in baselines; and a calibration command that publishes Cohen's kappa from human-authored JSONL.
- A deterministic online evaluation sampler backed by the durable worker queue, persistent online
  answer/judge records, generation and judge Prometheus metrics, and a provisioned Grafana quality
  dashboard for judge scores, outcomes, latency, cache behavior, and cost.
- A weekly and manually dispatchable scheduled workflow that restores the cross-domain index
  snapshots, runs full retrieval plus a 200-query answer/judge sample on each dataset's strongest
  retrieval variant, uploads reproducible JSON and Markdown reports, gates against a published
  answer baseline when present, and opens a deduplicated issue on regression.
- The first Phase 3 AWS foundation: separate Terraform bootstrap and application-state roots,
  repository-scoped GitHub OIDC plan/apply roles, native S3 state locking, a two-AZ VPC with an
  explicit NAT-cost mode, private RDS PostgreSQL with RDS-managed credentials, versioned encrypted
  artifact storage, immutable ECR images, scoped ECS runtime roles, and CloudWatch log groups.
  Infrastructure changes validate without credentials on every pull request, plan after merge to
  protected `dev`, and apply only through the protected `production` GitHub environment. See
  [`docs/aws_deployment.md`](docs/aws_deployment.md).

All three real corpora are fully ingested in live PostgreSQL with ready indexes: SciFact has 5,183
documents and 300 test queries, NFCorpus has 3,633 and 323, and FiQA has 57,638 and 648. Every
variant has a complete report and every dataset has a seed-42, 50-query baseline. At the largest
scale, FiQA's BM25 artifact is 76 MB and its embedding rows occupy approximately 89 MB before table
and index overhead. A controlled interruption preserved 18,392 completed embeddings; the resumed
invocation inserted only the remaining 39,246, and a final rerun inserted zero. FiQA's full-run P95
dense retrieval was 67 ms; reranking dominated at 3.11 s P95, well above the phase-1 600 ms target.

The checked-in `fixtures/tiny-beir` corpus backs the integration tests and needs no download. The
suite passes 169 tests along with Ruff and strict mypy. Provider calls are exercised with recorded
HTTP responses, so the default suite is deterministic and has no API spend. The complete core
Compose stack has also been validated on Apple Silicon: the API and PostgreSQL report healthy, the
migration exits successfully, the worker polls for jobs, Prometheus scrapes application metrics,
Tempo accepts traces, and the provisioned Grafana dashboard displays live metrics. A retrieval run
executed inside the Compose stack also passed the gate against the packaged, read-only fixture
baseline.

## Getting started

Python 3.13 is required.

```bash
python3.13 -m venv .venv
source .venv/bin/activate
make install check
```

Run the API locally:

```bash
make run
```

Liveness and readiness are at `http://127.0.0.1:8000/healthz` and `http://127.0.0.1:8000/readyz`.

Validated retrieval variants, model profiles, pricing, and regression thresholds live under
`config/`. Runtime settings use the `RAGOPS_` environment prefix; for example,
`RAGOPS_DATABASE_URL` overrides the local PostgreSQL URL. See `.env.example` for the full set.

ECS can inject an RDS-generated Secrets Manager document without constructing a URL in Terraform:
set `RAGOPS_DATABASE_HOST`, `RAGOPS_DATABASE_PORT`, `RAGOPS_DATABASE_NAME`,
`RAGOPS_DATABASE_USER`, and `RAGOPS_DATABASE_PASSWORD`. The application safely URL-encodes the
credentials and requires TLS by default. Component fields and `RAGOPS_DATABASE_URL` are mutually
exclusive.

Setting `RAGOPS_ARTIFACT_BUCKET` enables S3 synchronization. API and worker startup hydrate BM25
indexes, ingestion also hydrates checksum-pinned dataset caches and publishes both caches and the
completed content-addressed index, and `ragops eval report` publishes its JSON and Markdown files.
`RAGOPS_ARTIFACT_S3_PREFIX` optionally scopes all keys to an environment. Model caches are excluded
because model weights are reproducible upstream dependencies rather than platform artifacts.

### Database

Database-backed commands require PostgreSQL with pgvector running at the configured
`RAGOPS_DATABASE_URL`. A connection-refused error means the database is not running; it is
independent of whether the virtual environment is active.

```bash
make db-upgrade
```

### Ingestion

```bash
.venv/bin/ragops ingest --dataset fixture
.venv/bin/ragops ingest --dataset scifact
.venv/bin/ragops ingest --dataset nfcorpus
.venv/bin/ragops ingest --dataset fiqa
```

The first real ingestion downloads the configured sentence-transformer weights into the artifact
directory. Re-running an unchanged ingestion reuses persisted documents, qrels, BM25 artifacts, and
embeddings, and an interrupted one resumes from its last committed batch. Dataset terms, snapshot
counts, and the FiQA empty-record edge case are documented in [`docs/data_card.md`](docs/data_card.md).

### Docker Compose on macOS

A GPU is not required. The default image uses CPU inference and builds natively on both Apple
Silicon (`arm64`) and Intel/NVIDIA hosts (`amd64`). Install Docker Desktop, give it at least 8 GB of
memory, and start the core stack:

```bash
make stack-up
docker compose ps
```

This builds the non-root `ragops` image, migrates PostgreSQL, and starts the API, worker,
OpenTelemetry Collector, Tempo, Prometheus, and Grafana. The local endpoints are:

| Service | URL |
|---|---|
| API | `http://localhost:8000` |
| PostgreSQL | `localhost:5433` |
| Prometheus | `http://localhost:9090` |
| Grafana | `http://localhost:3000` (admin/admin) |
| Tempo API | `http://localhost:3200` |

The first image build downloads the CPU PyTorch stack and can take several minutes. Model weights
are downloaded on the first ingestion and persist under `artifacts/models`. Reranking is much slower
on CPU than on an NVIDIA GPU, but this affects evaluation runtime rather than Docker correctness.

Langfuse v4 and its ClickHouse, Redis, MinIO, and PostgreSQL dependencies are an optional profile
because the full stack needs substantially more memory. Allocate at least 16 GB to Docker Desktop
before starting it:

```bash
make stack-up-full
```

Langfuse is then available at `http://localhost:3001`. The credentials embedded in `compose.yaml`
are intentionally local-development values and must never be reused in a deployed environment.
Stop either stack with `make stack-down`; volumes are retained.

### Search

```bash
curl http://127.0.0.1:8000/v1/search \
  --header 'content-type: application/json' \
  --data '{"query":"Vitamin C health effects","dataset":"scifact","variant":"hybrid_rrf","k":10}'
```

Responses include document text, final ranks, every available stage score, per-stage latencies, the
variant configuration hash, and a trace identifier. Embedding and reranker models load on first use.

### Cited answers

Set `RAGOPS_OPENAI_API_KEY`, ingest the requested dataset, and call the same retrieval variants
through the cited-answer endpoint:

```bash
export RAGOPS_OPENAI_API_KEY='your-key'
curl http://127.0.0.1:8000/v1/answer \
  --header 'content-type: application/json' \
  --data '{"query":"Vitamin C health effects","dataset":"scifact","variant":"dense_bge_small","generator_profile":"default"}'
```

The default generator is the pinned `gpt-5.4-mini-2026-03-17` snapshot. The response contains the
exact retrieved contexts, stable citations, validation outcome, model and prompt hashes, token use,
incremental cost, provider request ID, and cache status. Repeating an unchanged request uses the
PostgreSQL response cache; OpenAI prompt-cache usage is recorded separately when reported by the
provider.

## Evaluation

### Running an evaluation

```bash
make eval-run \
  DATASET=scifact \
  VARIANTS=bm25,dense_bge_small,hybrid_rrf,hybrid_rrf_rerank \
  SAMPLE_SIZE=50 \
  SEED=42
```

The equivalent direct invocation, which works without activating the virtual environment:

```bash
.venv/bin/ragops eval run \
  --dataset scifact \
  --variants bm25,dense_bge_small,hybrid_rrf,hybrid_rrf_rerank \
  --sample-size 50 \
  --seed 42
```

Omit `--sample-size` to evaluate every query. The command creates a versioned run, validates the
selected variant hashes, persists each query/variant result as it completes, and prints the final
run record as JSON. Re-entering the runner for an interrupted run skips results already committed.

### Reports

```bash
.venv/bin/ragops eval report <run_id>
.venv/bin/ragops eval report <run_id> --format json
```

The report prints retrieval quality with 95% confidence intervals, per-stage latency percentiles,
and a paired-bootstrap comparison of every variant pair on every metric. Each rendered run is
archived to `evals/runs/<run_id>/report.md` and `report.json`, so results stay reviewable in a diff
and outlive the database they were computed from. Pass `--output-dir` to archive elsewhere or
`--no-save` to print without writing. Reports are seeded and byte-identical across runs.

### Baselines and the regression gate

Record a completed run as the committed reference for its dataset, then gate later runs against it.
When no path is supplied, both commands select `evals/baselines/<dataset>.json` from the run:

```bash
.venv/bin/ragops eval baseline <run_id>
.venv/bin/ragops eval gate <run_id>
```

`eval gate` prints a per-metric diff and exits non-zero when any metric falls further below the
baseline than `config/thresholds.yaml` allows, which is what fails a build:

| Exit code | Meaning |
|---|---|
| 0 | Every gated metric is within tolerance |
| 1 | A metric regressed past its tolerance |
| 2 | The comparison is unusable, so no quality claim was made |

The gate refuses to compare a run against a baseline measured on a different benchmark: the dataset,
split, and query sample must match, and when queries are sampled the seed must match too, since a
different seed selects a different subset. A full-dataset run ignores the seed because it evaluates
every query regardless. Exit code 2 also covers a missing or outdated baseline file, so a
misconfigured gate can never be mistaken for a passing one.

Only metrics that appear in both the baseline and the threshold file are gated; a variant present in
the run but absent from the baseline is treated as new and ungated, while a baselined metric missing
from the run is rejected rather than silently passed. Baselines are updated the way a snapshot test
is: through a reviewed pull request that carries the new run identifier and a justification.

Every run also pins a content-derived index fingerprint per variant. The fingerprint covers the
corpus, embedding and HNSW configuration, and BM25 artifact; unlike a database UUID it is stable
when an identical index is rebuilt in CI. The gate rejects a different fingerprint or variant
configuration hash before comparing scores.

The pull-request workflow exercises this path first against the checked-in two-query fixture as a
fast correctness canary. A matrix then runs all four variants for the deterministic 50-query
SciFact, NFCorpus, and FiQA slices and gates them against `evals/baselines/<dataset>.json`. Each job
uploads its JSON and Markdown reports, including the per-metric gate diff. Reproduce any matrix job
with `--sample-size 50` and `--seed 42`; the baseline itself pins the sample definition, variant
hashes, and index fingerprint.

Hosted jobs cache each corpus's logical PostgreSQL snapshot separately from model weights. The
index-cache key covers the dataset and model manifests, migrations, locked dependencies, and the
code that constructs and persists an index. A cache hit restores the snapshot and reruns ingestion
as an idempotency check. A miss performs the full checksum-validated download and embedding build,
saves the cache immediately, and then evaluates. The workflow also supports manual dispatch so a
maintainer can warm new cache keys before opening retrieval-changing pull requests.

### Answer evaluation and judge calibration

Run retrieval across all variants while generating only for the domain's selected answer variant:

```bash
.venv/bin/ragops eval run \
  --dataset scifact \
  --variants bm25,dense_bge_small,hybrid_rrf,hybrid_rrf_rerank \
  --generation \
  --generation-sample-size 200 \
  --generation-variants dense_bge_small \
  --generator-profile default \
  --judge-profiles default,secondary
```

SciFact automatically uses `scifact-v1`; NFCorpus and FiQA use `answer-v1`. The scheduled workflow
uses the same 200-query seed-42 slices and selects `dense_bge_small` for SciFact/FiQA and
`hybrid_rrf_rerank` for NFCorpus, matching the cross-domain retrieval results above.

Judge agreement is intentionally not self-labeled. After a human reviews roughly 100 mixed-domain
rows following [`evals/calibration/README.md`](evals/calibration/README.md), publish the report with:

```bash
.venv/bin/ragops eval calibrate \
  --labels evals/calibration/labels.jsonl \
  --judge-profiles default,secondary
```

This writes `evals/calibration/report.md` with faithfulness and relevance Cohen's kappa. No judge
quality claim should be published until those labels have been independently reviewed.

### Queued runs and workers

`eval run` executes in the current process, which suits a laptop and CI. For anything longer, the
API queues the work and a worker executes it:

```bash
curl http://127.0.0.1:8000/v1/evals \
  --header 'content-type: application/json' \
  --data '{"dataset":"scifact","variants":["bm25","hybrid_rrf"],"sample_size":50,"seed":42}'
```

The request returns `202 Accepted` with the created run and a `Location` header; the API never runs
an evaluation inside a request. The run row and its queue job are written in one transaction, so a
crash cannot leave a queued run that no worker will claim. Poll progress with
`GET /v1/evals/{run_id}`.

```bash
.venv/bin/ragops worker
.venv/bin/ragops worker --once     # process at most one job, then exit
```

Workers claim rows from the `jobs` table with `FOR UPDATE SKIP LOCKED`, so several can run
concurrently without coordinating. A claimed job holds a time-limited lease that the worker renews
while the run executes, which keeps a long evaluation from being handed to a second worker
mid-flight. A failed job returns to the queue with its error recorded until its attempt limit is
reached, and because the runner skips work already committed, a redelivered job resumes from the last
persisted query rather than restarting. `SIGINT` and `SIGTERM` stop the worker after the job in
flight finishes.

## Remaining work

Phase 2's local implementation is complete, but its empirical acceptance evidence is deliberately
not fabricated. A maintainer still needs to add the `OPENAI_API_KEY` Actions secret, run the
scheduled workflow to publish the three answer reports and their reviewed baselines, author and
review the human calibration labels, publish the kappa report, and record answer latency on the
reference hardware. A complete answer trace should also be confirmed in the optional Langfuse
profile; OpenTelemetry spans and model/cost attributes are emitted, but that UI check requires a
configured Langfuse project.

Phase 3's AWS foundation is implemented, including remote state, OIDC, networking, ECR, private
RDS, S3, Secrets Manager references, IAM, and log retention. The next deployment slice is ECS: API,
worker, migration and CLI task definitions, ALB routing, ADOT sidecars, CloudWatch dashboards and
alarms, image build/Trivy scanning, deployment rollout, and a deployed evaluation run. Before those
tasks can be stateless, the application also needs an explicit S3 artifact hydration/publication
contract and environment-composed RDS credentials.

Final portfolio packaging remains after deployment: ADRs, model card, screenshots, release tag,
and the external `deep-research` scoring adapter. The real-dataset CI matrix is slow the first time
a content-derived cache key is built—especially for FiQA—but subsequent runs restore the durable
index snapshots.

## Design

The full design, including the AWS target architecture, the evaluation cost envelope, and the
rollout plan, is documented in
[`arch_plan/rag-eval-platform-plan.md`](arch_plan/rag-eval-platform-plan.md).
