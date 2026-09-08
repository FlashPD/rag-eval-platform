"""Configuration-driven retrieval pipeline executor."""

from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Protocol
from uuid import uuid4

from opentelemetry.trace import get_tracer

from ragops.config import DatasetCatalog, VariantRegistry
from ragops.contracts import RankedHit, SearchRequest, SearchResponse, StageTiming
from ragops.ingestion.embedders import QueryEmbedder
from ragops.retrieval.errors import CompatibleIndexNotFoundError
from ragops.retrieval.fusion import reciprocal_rank_fusion
from ragops.retrieval.rerank import Reranker
from ragops.retrieval.sparse import SparseRetriever
from ragops.retrieval.store import SearchDataStore
from ragops.retrieval.types import StageHit
from ragops.telemetry import record_retrieval_stage


class SearchExecutor(Protocol):
    async def search(self, request: SearchRequest) -> SearchResponse: ...


class RetrievalPipeline:
    def __init__(
        self,
        *,
        datasets: DatasetCatalog,
        variants: VariantRegistry,
        store: SearchDataStore,
        sparse_retriever: SparseRetriever,
        query_embedders: Mapping[str, QueryEmbedder],
        rerankers: Mapping[str, Reranker],
    ) -> None:
        self._datasets = datasets
        self._variants = variants
        self._store = store
        self._sparse_retriever = sparse_retriever
        self._query_embedders = query_embedders
        self._rerankers = rerankers
        self._tracer = get_tracer(__name__)

    @asynccontextmanager
    async def _stage(
        self,
        name: str,
        timings: list[StageTiming],
        *,
        dataset: str,
        variant: str,
    ) -> AsyncIterator[None]:
        started = perf_counter()
        with self._tracer.start_as_current_span(name):
            try:
                yield
            finally:
                duration_ms = (perf_counter() - started) * 1_000
                timings.append(StageTiming(stage=name, duration_ms=duration_ms))
                record_retrieval_stage(
                    stage=name,
                    duration_ms=duration_ms,
                    dataset=dataset,
                    variant=variant,
                )

    async def search(self, request: SearchRequest) -> SearchResponse:
        variant = self._variants.get(request.variant)
        manifest = self._datasets.get(request.dataset)
        timings: list[StageTiming] = []
        with self._tracer.start_as_current_span("search") as search_span:
            search_span.set_attribute("rag.dataset", request.dataset)
            search_span.set_attribute("rag.variant", request.variant)
            index_version = await self._store.resolve_index(
                dataset_name=request.dataset,
                dataset_version=manifest.version,
                split=manifest.default_split,
                embedding_model=variant.dense.model if variant.dense is not None else None,
            )
            stage_scores: dict[str, dict[str, float]] = {}
            sparse_hits: tuple[StageHit, ...] = ()
            dense_hits: tuple[StageHit, ...] = ()

            if variant.sparse is not None:
                async with self._stage(
                    "sparse_retrieve",
                    timings,
                    dataset=request.dataset,
                    variant=request.variant,
                ):
                    sparse_hits = await self._sparse_retriever.retrieve(
                        request.query,
                        artifact_hash=index_version.bm25_artifact_hash,
                        k=variant.sparse.k,
                    )
                self._record_scores(stage_scores, "sparse_score", sparse_hits)

            if variant.dense is not None:
                try:
                    embedder = self._query_embedders[variant.dense.model]
                except KeyError as error:
                    raise CompatibleIndexNotFoundError(
                        f"query embedder is not configured: {variant.dense.model}"
                    ) from error
                async with self._stage(
                    "dense_embed_query",
                    timings,
                    dataset=request.dataset,
                    variant=request.variant,
                ):
                    query_embedding = await embedder.encode_query(request.query)
                if (
                    embedder.model_id != index_version.embedding_model
                    or embedder.normalized != index_version.normalized
                    or len(query_embedding) != index_version.dimension
                ):
                    raise CompatibleIndexNotFoundError(
                        "query embedder does not match the selected index configuration"
                    )
                async with self._stage(
                    "dense_retrieve",
                    timings,
                    dataset=request.dataset,
                    variant=request.variant,
                ):
                    dense_hits = await self._store.dense_search(
                        index_version.id,
                        query_embedding,
                        k=variant.dense.k,
                    )
                self._record_scores(stage_scores, "dense_score", dense_hits)

            if variant.fusion is not None:
                if variant.fusion.method != "rrf":
                    raise ValueError(f"unsupported fusion method: {variant.fusion.method}")
                async with self._stage(
                    "fuse", timings, dataset=request.dataset, variant=request.variant
                ):
                    current = reciprocal_rank_fusion((sparse_hits, dense_hits), k=variant.fusion.k)
                self._record_scores(stage_scores, "fused_score", current)
            else:
                current = sparse_hits or dense_hits

            if variant.rerank is not None:
                candidate_hits = current[: variant.rerank.candidates]
                candidate_ids = [hit.document_id for hit in candidate_hits]
                async with self._stage(
                    "rerank", timings, dataset=request.dataset, variant=request.variant
                ):
                    documents = await self._store.load_documents(
                        index_version.corpus_version_id, candidate_ids
                    )
                    try:
                        reranker = self._rerankers[variant.rerank.model]
                    except KeyError as error:
                        raise CompatibleIndexNotFoundError(
                            f"reranker is not configured: {variant.rerank.model}"
                        ) from error
                    ordered_documents = [documents[document_id] for document_id in candidate_ids]
                    scores = await reranker.score(request.query, ordered_documents)
                    if len(scores) != len(candidate_hits):
                        raise ValueError(
                            "reranker returned a different number of scores than inputs"
                        )
                    original_ranks = {
                        hit.document_id: rank for rank, hit in enumerate(candidate_hits)
                    }
                    reranked = tuple(
                        sorted(
                            (
                                StageHit(document_id=hit.document_id, score=float(score))
                                for hit, score in zip(candidate_hits, scores, strict=True)
                            ),
                            key=lambda hit: (
                                -hit.score,
                                original_ranks[hit.document_id],
                                hit.document_id,
                            ),
                        )
                    )
                    # Reranking reorders the candidate window rather than truncating the
                    # result list: the top `keep` hits are promoted and every remaining
                    # candidate keeps its fused order below them. Retrieval depth therefore
                    # stays identical across variants, so depth-100 metrics remain
                    # comparable between a reranked variant and its unreranked parent.
                    promoted = reranked[: variant.rerank.keep]
                    promoted_ids = {hit.document_id for hit in promoted}
                    current = promoted + tuple(
                        hit for hit in current if hit.document_id not in promoted_ids
                    )
                self._record_scores(stage_scores, "rerank_score", reranked)

            final_hits = current[: request.k]
            async with self._stage(
                "hydrate_results", timings, dataset=request.dataset, variant=request.variant
            ):
                documents = await self._store.load_documents(
                    index_version.corpus_version_id,
                    [hit.document_id for hit in final_hits],
                )
            trace_context = search_span.get_span_context()
            trace_id = f"{trace_context.trace_id:032x}" if trace_context.trace_id else uuid4().hex
            return SearchResponse(
                hits=tuple(
                    RankedHit(
                        document_id=hit.document_id,
                        title=documents[hit.document_id].title,
                        text=documents[hit.document_id].text,
                        rank=rank,
                        score=hit.score,
                        stage_scores=stage_scores[hit.document_id],
                    )
                    for rank, hit in enumerate(final_hits, start=1)
                ),
                timings=tuple(timings),
                trace_id=trace_id,
                variant_hash=variant.configuration_hash,
                index_fingerprint=index_version.fingerprint,
            )

    @staticmethod
    def _record_scores(
        scores: dict[str, dict[str, float]], name: str, hits: Sequence[StageHit]
    ) -> None:
        for hit in hits:
            scores.setdefault(hit.document_id, {})[name] = hit.score
