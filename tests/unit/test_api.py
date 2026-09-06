import asyncio

import httpx

from ragops.api import app, create_app
from ragops.contracts import SearchRequest, SearchResponse
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
