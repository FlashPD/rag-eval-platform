# RAG Evaluation & Observability Platform

`ragops` makes retrieval quality measurable, reproducible, and safe to change. It indexes public
information-retrieval benchmarks, serves several swappable retrieval strategies behind one API, and
scores them with deterministic metrics, confidence intervals, and a regression gate that fails a
build when quality drops.

The product is the measurement, not the search.

## Results

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
- A resumable BEIR ingestion pipeline for the checked-in fixture and the checksum-pinned SciFact
  dataset. It securely downloads and validates archives, loads documents, queries, and qrels in
  committed batches, creates content-addressed BM25 artifacts, and persists sentence-transformer
  embeddings with recoverable index-build progress.
- Sparse BM25, dense pgvector, reciprocal-rank-fusion hybrid, and cross-encoder reranked retrieval
  pipelines. Search results preserve stage scores, deterministic ranks, stage latencies,
  configuration hashes, and trace identifiers. Reranking reorders its candidate window instead of
  truncating the result list, so every variant retrieves to the same depth and deep metrics stay
  comparable.
- A `POST /v1/search` endpoint with validated request and response schemas, API error mapping, lazy
  model loading, OpenTelemetry spans, and health and readiness endpoints.
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
- Provenance on every run: git commit, container image digest, dataset, split, sample size, seed,
  and the configuration hash of each variant.

SciFact is fully ingested against live PostgreSQL at 5,183 documents, 300 queries, and 339 qrels,
with all 5,183 embeddings persisted and the index version marked ready. All four retrieval variants
have been evaluated across the complete test set with real model weights, and evaluations have been
submitted over HTTP and executed by a worker end to end. The checked-in `fixtures/tiny-beir` corpus
backs the integration tests and needs no download. The suite passes 98 tests along with Ruff, strict
mypy, dependency, migration-head, and OpenAPI checks.

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
```

The first real ingestion downloads the configured sentence-transformer weights into the artifact
directory. Re-running an unchanged ingestion reuses persisted documents, qrels, BM25 artifacts, and
embeddings, and an interrupted one resumes from its last committed batch.

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

Record a completed run as the committed reference for its dataset, then gate later runs against it:

```bash
.venv/bin/ragops eval baseline <run_id> --output evals/baselines/main.json
.venv/bin/ragops eval gate <run_id> --baseline evals/baselines/main.json
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

The pull-request workflow exercises this path end to end against the checked-in two-query fixture:
it starts pgvector, applies migrations, ingests and indexes the fixture, runs BM25, and gates the
result against `evals/baselines/fixture.json`. This is a fast correctness canary; the 50-query
SciFact baseline remains the quality regression benchmark used for retrieval changes.

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

## Not built yet

The CPU-first Docker image, core Compose stack, optional full Langfuse profile, provisioned service
dashboard, OpenTelemetry trace export, Prometheus metrics, pull-request smoke gate, and portable
index provenance are implemented. The Compose stack still needs a runtime validation on a machine
with Docker Desktop; static and application tests do not pull or start its service images.

Generation and LLM-as-judge scoring, the online evaluation sampler, the NFCorpus and FiQA corpora,
and the Terraform path to ECS are still ahead. The PR workflow uses the tiny fixture for fast
end-to-end coverage; promoting the 50-query SciFact gate into hosted CI will require a durable cache
for its corpus indexes and embeddings so every pull request does not rebuild them.

## Design

The full design, including the AWS target architecture, the evaluation cost envelope, and the
rollout plan, is documented in
[`arch_plan/rag-eval-platform-plan.md`](arch_plan/rag-eval-platform-plan.md).
