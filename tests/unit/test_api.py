import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx

from ragops.api import app, create_app
from ragops.contracts import (
    EvalProgress,
    EvalRun,
    EvalRunSpec,
    EvalRunState,
    SearchRequest,
    SearchResponse,
)
from ragops.retrieval.errors import DatasetNotIngestedError


class FakeSearchService:
    async def search(self, request: SearchRequest) -> SearchResponse:
        return SearchResponse(
            hits=(),
            timings=(),
            trace_id="a" * 32,
            variant_hash="b" * 64,
        )


class MissingDatasetSearchService:
    async def search(self, request: SearchRequest) -> SearchResponse:
        raise DatasetNotIngestedError("dataset is not ingested: missing")


async def get(path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path)


def test_liveness() -> None:
    response = asyncio.run(get("/healthz"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness() -> None:
    response = asyncio.run(get("/readyz"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_search_endpoint_returns_typed_response() -> None:
    async def request() -> httpx.Response:
        application = create_app(FakeSearchService())
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/v1/search",
                json={
                    "query": "What is the red planet?",
                    "dataset": "fixture",
                    "variant": "bm25",
                    "k": 10,
                },
            )

    response = asyncio.run(request())

    assert response.status_code == 200
    assert response.json()["trace_id"] == "a" * 32


def test_search_endpoint_maps_missing_dataset_to_not_found() -> None:
    async def request() -> httpx.Response:
        application = create_app(MissingDatasetSearchService())
        transport = httpx.ASGITransport(app=application)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/v1/search",
                json={
                    "query": "question",
                    "dataset": "missing",
                    "variant": "bm25",
                },
            )

    response = asyncio.run(request())

    assert response.status_code == 404
    assert response.json() == {"detail": "dataset is not ingested: missing"}


class FakeEvaluationService:
    def __init__(self, run: EvalRun | None = None, error: Exception | None = None) -> None:
        self.run = run
        self.error = error
        self.submitted: list[EvalRunSpec] = []

    async def submit(self, spec: EvalRunSpec) -> EvalRun:
        self.submitted.append(spec)
        if self.error is not None:
            raise self.error
        assert self.run is not None
        return self.run

    async def get(self, run_id: UUID) -> EvalRun:
        if self.error is not None:
            raise self.error
        assert self.run is not None
        return self.run


def queued_run(spec: EvalRunSpec) -> EvalRun:
    return EvalRun(
        id=uuid4(),
        spec=spec,
        state=EvalRunState.QUEUED,
        progress=EvalProgress(),
        created_at=datetime.now(UTC),
    )


async def call(application: object, method: str, path: str, **kwargs: object) -> httpx.Response:
    transport = httpx.ASGITransport(app=application)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.request(method, path, **kwargs)


def test_submit_evaluation_queues_a_run_without_executing_it() -> None:
    spec = EvalRunSpec(dataset="scifact", variants=("bm25",), sample_size=50, seed=42)
    service = FakeEvaluationService(queued_run(spec))
    application = create_app(FakeSearchService(), service)

    response = asyncio.run(
        call(
            application,
            "POST",
            "/v1/evals",
            json={
                "dataset": "scifact",
                "variants": ["bm25"],
                "sample_size": 50,
                "seed": 42,
            },
        )
    )

    assert response.status_code == 202
    body = response.json()
    assert body["state"] == "queued"
    assert body["progress"]["completed_queries"] == 0
    assert response.headers["Location"] == f"/v1/evals/{body['id']}"
    assert service.submitted == [spec]


def test_submit_evaluation_maps_an_unknown_dataset_to_not_found() -> None:
    service = FakeEvaluationService(error=KeyError("dataset is not configured: nope"))
    application = create_app(FakeSearchService(), service)

    response = asyncio.run(
        call(
            application,
            "POST",
            "/v1/evals",
            json={"dataset": "nope", "variants": ["bm25"]},
        )
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "dataset is not configured: nope"}


def test_submit_evaluation_rejects_a_spec_the_service_will_not_run() -> None:
    service = FakeEvaluationService(
        error=ValueError("retrieval evaluation cannot enable generation")
    )
    application = create_app(FakeSearchService(), service)

    response = asyncio.run(
        call(
            application,
            "POST",
            "/v1/evals",
            json={
                "dataset": "scifact",
                "variants": ["bm25"],
                "generation_enabled": True,
                "generator_profile": "default",
            },
        )
    )

    assert response.status_code == 422


def test_reading_an_evaluation_run_reports_its_progress() -> None:
    spec = EvalRunSpec(dataset="scifact", variants=("bm25",))
    run = queued_run(spec)
    application = create_app(FakeSearchService(), FakeEvaluationService(run))

    response = asyncio.run(call(application, "GET", f"/v1/evals/{run.id}"))

    assert response.status_code == 200
    assert response.json()["id"] == str(run.id)


def test_reading_a_missing_evaluation_run_is_not_found() -> None:
    service = FakeEvaluationService(error=KeyError("evaluation run not found: x"))
    application = create_app(FakeSearchService(), service)

    response = asyncio.run(call(application, "GET", f"/v1/evals/{uuid4()}"))

    assert response.status_code == 404
