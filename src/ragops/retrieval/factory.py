"""Production construction of retrieval pipeline dependencies."""

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ragops.config import ConfigBundle
from ragops.ingestion.embedders import QueryEmbedder, SentenceTransformerEmbedder
from ragops.retrieval.pipeline import RetrievalPipeline
from ragops.retrieval.rerank import CrossEncoderReranker, Reranker
from ragops.retrieval.sparse import Bm25sSparseRetriever
from ragops.retrieval.store import SqlAlchemySearchDataStore


def build_retrieval_pipeline(
    bundle: ConfigBundle,
    sessions: async_sessionmaker[AsyncSession],
    *,
    artifact_root: Path,
    device: str | None = None,
    model_cache_directory: Path | None = None,
) -> RetrievalPipeline:
    embedding_profiles = {profile.model: profile for profile in bundle.models.embeddings.values()}
    reranker_profiles = {profile.model: profile for profile in bundle.models.rerankers.values()}

    dense_model_ids = {
        variant.dense.model
        for variant in bundle.variants.variants.values()
        if variant.dense is not None
    }
    reranker_model_ids = {
        variant.rerank.model
        for variant in bundle.variants.variants.values()
        if variant.rerank is not None
    }
    missing_embeddings = dense_model_ids - embedding_profiles.keys()
    missing_rerankers = reranker_model_ids - reranker_profiles.keys()
    if missing_embeddings or missing_rerankers:
        raise ValueError(
            "variant models are missing from the model catalog: "
            f"embeddings={sorted(missing_embeddings)}, rerankers={sorted(missing_rerankers)}"
        )
    invalid_dimensions = {
        model_id: embedding_profiles[model_id].dimension
        for model_id in dense_model_ids
        if embedding_profiles[model_id].dimension != 384
    }
    if invalid_dimensions:
        raise ValueError(f"v1 retrieval requires 384-dimensional embeddings: {invalid_dimensions}")

    query_embedders: dict[str, QueryEmbedder] = {
        model_id: SentenceTransformerEmbedder(
            model_id,
            normalized=embedding_profiles[model_id].normalize,
            device=device,
            cache_directory=model_cache_directory,
        )
        for model_id in dense_model_ids
    }
    rerankers: dict[str, Reranker] = {
        model_id: CrossEncoderReranker(
            model_id,
            device=device,
            cache_directory=model_cache_directory,
        )
        for model_id in reranker_model_ids
    }
    return RetrievalPipeline(
        datasets=bundle.datasets,
        variants=bundle.variants,
        store=SqlAlchemySearchDataStore(sessions),
        sparse_retriever=Bm25sSparseRetriever(artifact_root / "bm25"),
        query_embedders=query_embedders,
        rerankers=rerankers,
    )
