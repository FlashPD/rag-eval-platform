import asyncio
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

import ragops.api as api_module
from ragops.api import app, create_app
from ragops.contracts import (
    AnswerRequest,
    AnswerResponse,
    CitationValidation,
    Confidence,
    EvalProgress,
    EvalRun,
    EvalRunSpec,
    EvalRunState,
    GenerationOutcome,
    Passage,
    SearchRequest,
    SearchResponse,
    TokenUsage,
)
from ragops.retrieval.errors import DatasetNotIngestedError


class FakeSearchService:
    async def search(self, request: SearchRequest) -> SearchResponse:
        return SearchResponse(
            hits=(),
            timings=(),
            trace_id="a" * 32,
            variant_hash="b" * 64,
            index_fingerprint="c" * 64,
        )


class FakeArtifactStore:
    def __init__(self) -> None:
        self.runtime_hydrations = 0

    async def hydrate_runtime(self) -> int:
        self.runtime_hydrations += 1
        return 0

    async def hydrate_ingestion(self) -> int:
        return 0

    async def publish_ingestion(self, bm25_artifact: object) -> int:
        return 0

    async def publish_report(self, run_id: object, files: object) -> int:
        return 0


class MissingDatasetSearchService:
    async def search(self, request: SearchRequest) -> SearchResponse:
        raise DatasetNotIngestedError("dataset is not ingested: missing")


class FakeAnswerService:
    def __init__(self) -> None:
        self.requests: list[AnswerRequest] = []

    async def answer(self, request: AnswerRequest) -> AnswerResponse:
        self.requests.append(request)
        return AnswerResponse(
            answer="Mars is the red planet [1].",
            citations=("[1]",),
            abstained=False,
            confidence=Confidence.HIGH,
            contexts=(
                Passage(
                    local_id="[1]",
                    document_id="mars",
                    title="Mars",
                    text="Mars is known as the red planet.",
                    retrieval_rank=1,
                    retrieval_score=1,
                ),
            ),
            usage=TokenUsage(input_tokens=10, output_tokens=5),
            outcome=GenerationOutcome.OK,
            trace_id="answer-trace",
            provider="openai",
            model="test-model",
            generator_configuration_hash="d" * 64,
            prompt_version="answer-v1",
            rendered_prompt_hash="e" * 64,
            citation_validation=CitationValidation(valid=True),
        )


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


def test_lifespan_hydrates_runtime_artifacts_before_building_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_store = FakeArtifactStore()
    bundle = api_module.load_config_bundle(api_module.Settings().configuration_directory)
    events: list[str] = []

    class FakeEngine:
        async def dispose(self) -> None:
            events.append("disposed")

    original_hydrate = artifact_store.hydrate_runtime

    async def record_hydration() -> int:
        events.append("hydrated")
        return await original_hydrate()

    artifact_store.hydrate_runtime = record_hydration  # type: ignore[method-assign]
    monkeypatch.setattr(api_module, "load_config_bundle", lambda _: bundle)
    monkeypatch.setattr(api_module, "create_engine", lambda _: FakeEngine())
    monkeypatch.setattr(api_module, "create_session_factory", lambda _: object())

    def build_search(*args: object, **kwargs: object) -> FakeSearchService:
        events.append("retrieval-built")
        return FakeSearchService()

    monkeypatch.setattr(api_module, "build_retrieval_pipeline", build_search)
    monkeypatch.setattr(api_module, "DatabaseEvaluationService", lambda *args, **kwargs: object())
    application = create_app(artifact_store=artifact_store)

    async def run_lifespan() -> None:
        async with application.router.lifespan_context(application):
            assert artifact_store.runtime_hydrations == 1

    asyncio.run(run_lifespan())

    assert events == ["hydrated", "retrieval-built", "disposed"]


def test_prometheus_metrics_include_http_requests() -> None:
    asyncio.run(get("/healthz"))

    response = asyncio.run(get("/metrics"))

    assert response.status_code == 200
    assert "ragops_http_server_requests_total" in response.text


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


def test_answer_endpoint_returns_a_provenance_complete_response() -> None:
    service = FakeAnswerService()
    application = create_app(FakeSearchService(), answer_service=service)

    response = asyncio.run(
        call(
            application,
            "POST",
            "/v1/answer",
            json={
                "query": "What is the red planet?",
                "dataset": "fixture",
                "variant": "bm25",
                "generator_profile": "default",
            },
        )
    )

    assert response.status_code == 200
    assert response.json()["provider"] == "openai"
    assert response.json()["citations"] == ["[1]"]
    assert service.requests[0].dataset == "fixture"


def test_answer_endpoint_is_explicitly_unavailable_without_a_provider() -> None:
    application = create_app(FakeSearchService())

    response = asyncio.run(
        call(
            application,
            "POST",
            "/v1/answer",
            json={"query": "Question", "dataset": "fixture", "variant": "bm25"},
        )
    )

    assert response.status_code == 503
    assert "RAGOPS_OPENAI_API_KEY" in response.json()["detail"]


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
