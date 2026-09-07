# RAG Evaluation & Observability Platform

`ragops` makes retrieval and generation quality measurable, reproducible, and safe to change.

## Implementation status

The project now has an end-to-end retrieval foundation:

- A Python 3.13 application scaffold with a root virtual environment, FastAPI, CLI tooling,
  pinned development dependencies, Ruff, strict mypy, pytest, pre-commit, and CI.
- Strict Pydantic contracts and validated YAML configuration for datasets, retrieval variants,
  models, pricing, evaluation thresholds, metrics, gates, judges, and jobs. Configuration is
  content-hashed so runs and index artifacts can be reproduced.
- An async SQLAlchemy and PostgreSQL persistence layer with Alembic migrations, fixed-size
  `vector(384)` embeddings, a cosine HNSW index, repositories, and UTC-normalized timestamps.
- A durable PostgreSQL job queue with idempotent submission, `FOR UPDATE SKIP LOCKED` claims,
  leases, heartbeats, retries, cancellation, and stale-worker protection.
- A resumable BEIR ingestion pipeline for the checked-in fixture and checksum-pinned SciFact
  dataset. It securely downloads and validates archives, loads documents, queries, and qrels in
  committed batches, creates content-addressed BM25 artifacts, and persists sentence-transformer
  embeddings with recoverable index-build progress.
- Sparse BM25, dense pgvector, reciprocal-rank-fusion hybrid, and cross-encoder reranked retrieval
  pipelines. Search results preserve stage scores, deterministic ranks, stage latencies,
  configuration hashes, and trace identifiers.
- A `POST /v1/search` HTTP endpoint with validated request and response schemas, API error mapping,
  lazy model loading, OpenTelemetry spans, and health and readiness endpoints.
- Deterministic per-query retrieval metrics (nDCG@10, Recall@10, Recall@100, and MRR@10) and a
  resumable retrieval evaluation runner with seeded query sampling, variant-hash validation,
  transactional result persistence, progress tracking, and cooperative cancellation.
- Evaluation aggregation with seeded bootstrap confidence intervals, paired-bootstrap significance
  testing between every variant pair, stage-level P50/P95 latency, and reproducible Markdown or
  JSON reports loaded from persisted query results and archived under `evals/runs/`.
- A regression gate that compares a completed run against a committed per-dataset baseline using
  the tolerances in `config/thresholds.yaml`, prints a per-metric diff, and exits non-zero on any
  breach, with baseline capture as a separate reviewable command.

The checked-in fixture has been ingested and searched end to end through the HTTP API. SciFact is
fully ingested against live PostgreSQL at 5,183 documents, 300 queries, and 339 qrels, with all
5,183 embeddings persisted and the index version marked ready. The four retrieval variants have
been evaluated end to end on that corpus with real model weights; the results below come from that
run. The suite currently passes 71 tests along with Ruff, strict mypy, dependency, migration-head,
and OpenAPI checks.

Generation, dashboards, and cloud deployment are outside the current implementation slice.

## Results

BEIR SciFact, 50-query deterministic sample (`--seed 42`), `BAAI/bge-small-en-v1.5` embeddings and
`cross-encoder/ms-marco-MiniLM-L-6-v2` reranking on CPU. Reproduce with the `eval run` command
below; the committed reference for these numbers is
[`evals/baselines/main.json`](evals/baselines/main.json).

| Variant | nDCG@10 | Recall@10 | Recall@100 | MRR@10 |
|---|---:|---:|---:|---:|
| `bm25` | 0.5671 | 0.6480 | 0.7960 | 0.5429 |
| `dense_bge_small` | 0.6808 | 0.8260 | 0.9800 | 0.6387 |
| `hybrid_rrf` | 0.6248 | 0.7460 | 1.0000 | 0.5914 |
| `hybrid_rrf_rerank` | 0.6534 | 0.8053 | 1.0000 | 0.6100 |

Stage latency, P50 and P95 in milliseconds over the same run:

| Variant | Sparse | Embed | Dense | Fuse | Rerank | Hydrate |
|---|---:|---:|---:|---:|---:|---:|
| `bm25` | 2.2 / 2.7 | — | — | — | — | 7.3 / 8.1 |
| `dense_bge_small` | — | 16.1 / 22.6 | 22.9 / 24.7 | — | — | 5.8 / 7.2 |
| `hybrid_rrf` | 1.7 / 2.0 | 15.2 / 18.8 | 20.8 / 24.6 | 0.4 / 0.5 | — | 5.8 / 6.8 |
| `hybrid_rrf_rerank` | 1.6 / 1.8 | 15.4 / 18.7 | 19.4 / 23.3 | 0.4 / 0.4 | 1152.6 / 1324.7 | 8.1 / 10.2 |

### Which differences are real

Point estimates alone cannot say whether one variant beats another. `eval report` runs a paired
bootstrap over queries for every variant pair and metric: it resamples queries and reads both
variants at the same query indices, so the interval measures the per-query gap rather than the
much wider spread of two independently estimated means. A difference counts as significant only
when its 95% interval excludes zero.

| Comparison | Metric | A - B | 95% CI | Significant |
|---|---|---:|---:|---|
| `bm25` vs `dense_bge_small` | nDCG@10 | -0.1137 | [-0.2146, -0.0021] | yes |
| `bm25` vs `dense_bge_small` | Recall@10 | -0.1780 | [-0.3080, -0.0480] | yes |
| `bm25` vs `dense_bge_small` | Recall@100 | -0.1840 | [-0.3040, -0.0759] | yes |
| `bm25` vs `dense_bge_small` | MRR@10 | -0.0959 | [-0.2097, +0.0138] | no |
| `dense_bge_small` vs `hybrid_rrf` | nDCG@10 | +0.0560 | [-0.0101, +0.1347] | no |
| `dense_bge_small` vs `hybrid_rrf_rerank` | nDCG@10 | +0.0274 | [-0.0608, +0.1194] | no |
| `hybrid_rrf` vs `hybrid_rrf_rerank` | nDCG@10 | -0.0285 | [-0.0936, +0.0319] | no |
| `hybrid_rrf` vs `hybrid_rrf_rerank` | Recall@100 | +0.0000 | [+0.0000, +0.0000] | no |

The full 24-row table is in
[`evals/runs/`](evals/runs/d10f154f-81a0-496e-8eec-0dcaf8c29746/report.md).

- **Dense retrieval beats BM25, and that result holds up.** The gap is significant on nDCG@10,
  Recall@10, and Recall@100. This is the expected direction for a scientific-claim benchmark where
  lexical overlap between a claim and its abstract is weak. MRR@10 is the one metric where the
  interval still crosses zero.
- **No hybrid or reranked variant is measurably better than dense retrieval alone.** Every
  comparison among `dense_bge_small`, `hybrid_rrf`, and `hybrid_rrf_rerank` has an interval
  spanning zero. The point estimates put dense slightly ahead on nDCG@10, but at 50 queries the
  data does not support claiming a winner among the three.
- **Cross-encoder reranking does not pay for itself here.** It costs roughly 1.15 s of P50 latency
  per query on CPU — two orders of magnitude more than any other stage — and buys no significant
  gain over `hybrid_rrf` on any metric. That is a result worth reporting, not hiding.
- Reranking reorders the candidate window rather than truncating the result list, so a reranked
  variant retrieves to the same depth as its unreranked parent. Their Recall@100 difference is
  exactly zero with a zero-width interval, which is the correct outcome: reranking reorders the
  same pool and cannot change deep recall.
- These are 50-query samples. Wider intervals here reflect sample size, not instability in the
  pipeline; the sample, the seed, and every variant hash are recorded with the run.


## Local development

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

The liveness and readiness endpoints are available at `http://127.0.0.1:8000/healthz`
and `http://127.0.0.1:8000/readyz`.

Validated retrieval variants, model profiles, pricing, and regression thresholds live under
`config/`. Runtime settings use the `RAGOPS_` environment prefix; for example,
`RAGOPS_DATABASE_URL` overrides the local PostgreSQL URL.

Apply database migrations with:

```bash
make db-upgrade
```

Database-backed commands require PostgreSQL with pgvector to be running at the configured
`RAGOPS_DATABASE_URL`. A connection-refused error means the database service is not running; it is
independent of whether the Python virtual environment is active.

Ingest the local fixture or the checksum-pinned SciFact benchmark with:

```bash
.venv/bin/ragops ingest --dataset fixture
.venv/bin/ragops ingest --dataset scifact
```

The first real ingestion downloads the configured sentence-transformer weights. Re-running an
unchanged ingestion reuses persisted documents, qrels, BM25 artifacts, and embeddings.

Search an ingested dataset through any configured retrieval variant:

```bash
curl http://127.0.0.1:8000/v1/search \
  --header 'content-type: application/json' \
  --data '{"query":"Vitamin C health effects","dataset":"scifact","variant":"hybrid_rrf","k":10}'
```

Search responses include document text, final ranks, every available stage score, per-stage
latencies, the variant configuration hash, and a trace identifier. Embedding and reranker models
load on their first use.

Run a retrieval evaluation in-process against an ingested dataset:

```bash
make eval-run \
  DATASET=scifact \
  VARIANTS=bm25,dense_bge_small,hybrid_rrf,hybrid_rrf_rerank \
  SAMPLE_SIZE=50 \
  SEED=42
```

The equivalent direct invocation, which also works without activating the virtual environment, is:

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

Render the completed run using the `id` printed by `eval run`:

```bash
.venv/bin/ragops eval report <run_id>
.venv/bin/ragops eval report <run_id> --format json
```

The report prints retrieval quality with 95% confidence intervals, per-stage latency percentiles,
and a paired-bootstrap comparison of every variant pair on every metric. Each rendered run is also
archived to `evals/runs/<run_id>/report.md` and `report.json`, so results stay reviewable in a diff
and outlive the database they were computed from. Pass `--output-dir` to archive elsewhere or
`--no-save` to print without writing.

Record a completed run as the committed reference for its dataset, then gate later runs against
it:

```bash
.venv/bin/ragops eval baseline <run_id> --output evals/baselines/main.json
.venv/bin/ragops eval gate <run_id> --baseline evals/baselines/main.json
```

`eval gate` prints a per-metric diff and exits non-zero when any metric falls further below the
baseline than `config/thresholds.yaml` allows, which is what fails a build. Only metrics that
appear in both the baseline and the threshold file are gated; a variant present in the run but
absent from the baseline is treated as new and ungated, while a baselined metric missing from the
run is rejected rather than silently passed. Baselines are updated the way a snapshot test is:
through a reviewed pull request that carries the new run identifier and a justification.

The v1 persistence layer uses fixed `vector(384)` embeddings with a cosine-distance HNSW
index. Evaluation work is dispatched through the `jobs` table: workers claim rows with
`FOR UPDATE SKIP LOCKED`, renew time-limited leases, and return failed work to the queue until
its configured attempt limit is reached.

The full design is documented in
[`arch_plan/rag-eval-platform-plan.md`](arch_plan/rag-eval-platform-plan.md).
