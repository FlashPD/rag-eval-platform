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

The checked-in fixture has been ingested and searched end to end through the HTTP API. The pinned
SciFact source has also been validated at 5,183 documents, 300 queries, and 339 qrels. The suite
currently passes 32 tests along with Ruff, strict mypy, dependency, migration-head, and OpenAPI
checks. Dense SQL and reranking behavior are covered with deterministic test substitutes; running
those paths against live PostgreSQL and downloaded model weights remains an integration step.

Generation, evaluation execution and reporting, regression gates, dashboards, and cloud deployment
are outside the current implementation slice.

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

Ingest the local fixture or the checksum-pinned SciFact benchmark with:

```bash
ragops ingest --dataset fixture
ragops ingest --dataset scifact
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

The v1 persistence layer uses fixed `vector(384)` embeddings with a cosine-distance HNSW
index. Evaluation work is dispatched through the `jobs` table: workers claim rows with
`FOR UPDATE SKIP LOCKED`, renew time-limited leases, and return failed work to the queue until
its configured attempt limit is reached.

The full design is documented in
[`arch_plan/rag-eval-platform-plan.md`](arch_plan/rag-eval-platform-plan.md).
