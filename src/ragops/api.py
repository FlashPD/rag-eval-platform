"""HTTP API for ragops."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncEngine

from ragops.artifact_store import ArtifactStore, build_artifact_store
from ragops.config import Settings, load_config_bundle
from ragops.contracts import (
    AnswerRequest,
    AnswerResponse,
    EvalRun,
    EvalRunSpec,
    SearchRequest,
    SearchResponse,
)
from ragops.evaluation import DatabaseEvaluationService, EvaluationService
from ragops.generation.factory import build_answer_service
from ragops.generation.service import AnswerService
from ragops.persistence import create_engine, create_session_factory
from ragops.provenance import resolve_git_commit, resolve_image_digest
from ragops.retrieval.errors import (
    ArtifactNotFoundError,
    CompatibleIndexNotFoundError,
    DatasetNotIngestedError,
    RetrievalLimitError,
)
from ragops.retrieval.factory import build_retrieval_pipeline
from ragops.retrieval.pipeline import SearchExecutor
from ragops.schemas import HealthResponse
from ragops.telemetry import configure_telemetry, instrument_fastapi, prometheus_response


def create_app(
    search_service: SearchExecutor | None = None,
    evaluation_service: EvaluationService | None = None,
    answer_service: AnswerService | None = None,
    *,
    artifact_store: ArtifactStore | None = None,
) -> FastAPI:
    """Build the FastAPI application."""

    settings = Settings()
    configure_telemetry(settings)

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        engine: AsyncEngine | None = None
        needs_search = application.state.search_service is None
        needs_evaluation = application.state.evaluation_service is None
        needs_answer = application.state.answer_service is None
        if needs_search or needs_evaluation:
            configured_store = artifact_store or build_artifact_store(settings)
            await configured_store.hydrate_runtime()
            bundle = load_config_bundle(settings.configuration_directory)
            engine = create_engine(settings.database_url)
            sessions = create_session_factory(engine)
            if needs_search:
                application.state.search_service = build_retrieval_pipeline(
                    bundle,
                    sessions,
                    artifact_root=settings.artifact_directory,
                    device=settings.model_device,
                    model_cache_directory=settings.model_cache_directory,
                )
            if needs_evaluation:
                application.state.evaluation_service = DatabaseEvaluationService(
                    sessions,
                    datasets=bundle.datasets,
                    variants=bundle.variants,
                    git_commit=resolve_git_commit(),
                    image_digest=resolve_image_digest(),
                )
            if needs_answer and settings.openai_api_key is not None:
                assert application.state.search_service is not None
                application.state.answer_service = build_answer_service(
                    bundle,
                    sessions,
                    search=application.state.search_service,
                    settings=settings,
                )
        try:
            yield
        finally:
            if engine is not None:
                await engine.dispose()

    application = FastAPI(
        title="RAG Evaluation & Observability Platform",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.search_service = search_service
    application.state.evaluation_service = evaluation_service
    application.state.answer_service = answer_service
    instrument_fastapi(application)

    @application.get("/healthz", tags=["operations"])
    async def health() -> HealthResponse:
        """Report whether the process is alive."""
        return HealthResponse(status="ok")

    @application.get("/readyz", tags=["operations"])
    async def readiness() -> HealthResponse:
        """Report whether the service is ready to accept requests."""
        return HealthResponse(status="ok")

    @application.get("/metrics", tags=["operations"], include_in_schema=False)
    async def metrics() -> Response:
        """Expose process and retrieval metrics for Prometheus."""
        return prometheus_response()

    @application.post("/v1/search", tags=["retrieval"])
    async def search(request: SearchRequest) -> SearchResponse:
        service: SearchExecutor | None = application.state.search_service
        if service is None:
            raise HTTPException(status_code=503, detail="retrieval service is not initialized")
        try:
            return await service.search(request)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error.args[0])) from error
        except DatasetNotIngestedError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except CompatibleIndexNotFoundError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ArtifactNotFoundError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except RetrievalLimitError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.post("/v1/answer", tags=["generation"])
    async def answer(request: AnswerRequest) -> AnswerResponse:
        service: AnswerService | None = application.state.answer_service
        if service is None:
            raise HTTPException(
                status_code=503,
                detail="answer generation is unavailable; configure RAGOPS_OPENAI_API_KEY",
            )
        try:
            return await service.answer(request)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error.args[0])) from error
        except DatasetNotIngestedError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except CompatibleIndexNotFoundError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ArtifactNotFoundError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except RetrievalLimitError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @application.post("/v1/evals", tags=["evaluation"], status_code=status.HTTP_202_ACCEPTED)
    async def submit_evaluation(request: EvalRunSpec, response: Response) -> EvalRun:
        """Queue an evaluation run for a worker and return the created record.

        The API never executes an evaluation inside a request; it writes the run and
        its job in one transaction and returns immediately.
        """
        service: EvaluationService | None = application.state.evaluation_service
        if service is None:
            raise HTTPException(status_code=503, detail="evaluation service is not initialized")
        try:
            run = await service.submit(request)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error.args[0])) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        response.headers["Location"] = f"/v1/evals/{run.id}"
        return run

    @application.get("/v1/evals/{run_id}", tags=["evaluation"])
    async def read_evaluation(run_id: UUID) -> EvalRun:
        """Report the current state and progress of one evaluation run."""
        service: EvaluationService | None = application.state.evaluation_service
        if service is None:
            raise HTTPException(status_code=503, detail="evaluation service is not initialized")
        try:
            return await service.get(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error.args[0])) from error

    return application


app = create_app()
