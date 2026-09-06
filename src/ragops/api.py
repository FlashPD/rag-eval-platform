"""HTTP API for ragops."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from sqlalchemy.ext.asyncio import AsyncEngine

from ragops.config import Settings, load_config_bundle
from ragops.contracts import SearchRequest, SearchResponse
from ragops.persistence import create_engine, create_session_factory
from ragops.retrieval.errors import (
    ArtifactNotFoundError,
    CompatibleIndexNotFoundError,
    DatasetNotIngestedError,
    RetrievalLimitError,
)
from ragops.retrieval.factory import build_retrieval_pipeline
from ragops.retrieval.pipeline import SearchExecutor
from ragops.schemas import HealthResponse


def create_app(search_service: SearchExecutor | None = None) -> FastAPI:
    """Build the FastAPI application."""

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        engine: AsyncEngine | None = None
        if application.state.search_service is None:
            settings = Settings()
            bundle = load_config_bundle(settings.configuration_directory)
            engine = create_engine(settings.database_url)
            application.state.search_service = build_retrieval_pipeline(
                bundle,
                create_session_factory(engine),
                artifact_root=settings.artifact_directory,
                device=settings.model_device,
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

    @application.get("/healthz", tags=["operations"])
    async def health() -> HealthResponse:
        """Report whether the process is alive."""
        return HealthResponse(status="ok")

    @application.get("/readyz", tags=["operations"])
    async def readiness() -> HealthResponse:
        """Report whether the service is ready to accept requests."""
        return HealthResponse(status="ok")

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

    return application


app = create_app()
