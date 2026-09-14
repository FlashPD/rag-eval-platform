"""Read-only bm25s artifact retrieval."""

import asyncio
import importlib
import threading
from pathlib import Path
from typing import Any, Protocol

from ragops.ingestion.hashing import hash_directory
from ragops.retrieval.errors import ArtifactNotFoundError
from ragops.retrieval.types import StageHit


class SparseRetriever(Protocol):
    async def retrieve(self, query: str, *, artifact_hash: str, k: int) -> tuple[StageHit, ...]: ...


class Bm25sSparseRetriever:
    def __init__(self, artifact_root: Path, *, verify_artifacts: bool = True) -> None:
        self._artifact_root = artifact_root
        self._verify_artifacts = verify_artifacts
        self._models: dict[str, Any] = {}
        self._load_lock = threading.Lock()

    def _load(self, artifact_hash: str) -> Any:
        with self._load_lock:
            cached = self._models.get(artifact_hash)
            if cached is not None:
                return cached
            artifact_path = self._artifact_root / artifact_hash
            if not artifact_path.is_dir():
                raise ArtifactNotFoundError(f"BM25 artifact not found: {artifact_hash}")
            if self._verify_artifacts and hash_directory(artifact_path) != artifact_hash:
                raise ArtifactNotFoundError(
                    f"BM25 artifact failed integrity check: {artifact_hash}"
                )
            bm25s: Any = importlib.import_module("bm25s")
            model = bm25s.BM25.load(artifact_path, load_corpus=True, mmap=True)
            self._models[artifact_hash] = model
            return model

    def _retrieve(self, query: str, artifact_hash: str, k: int) -> tuple[StageHit, ...]:
        model = self._load(artifact_hash)
        corpus_size = len(model.corpus)
        if corpus_size == 0:
            return ()
        bm25s: Any = importlib.import_module("bm25s")
        query_tokens = bm25s.tokenize([query], stopwords="en", show_progress=False)
        documents, scores = model.retrieve(
            query_tokens,
            k=min(k, corpus_size),
            show_progress=False,
        )
        return tuple(
            StageHit(document_id=str(document["id"]), score=float(score))
            for document, score in zip(documents[0], scores[0], strict=True)
        )

    async def retrieve(self, query: str, *, artifact_hash: str, k: int) -> tuple[StageHit, ...]:
        return await asyncio.to_thread(self._retrieve, query, artifact_hash, k)
