"""Content-addressed BM25 artifact construction."""

import importlib
import shutil
import tempfile
from pathlib import Path
from typing import Any, Protocol

from ragops.contracts import ArtifactReference, SourceDocument
from ragops.ingestion.hashing import hash_directory


class SparseIndexBuilder(Protocol):
    def build(
        self, documents: tuple[SourceDocument, ...], artifact_root: Path
    ) -> ArtifactReference: ...


class Bm25sIndexBuilder:
    """Build an immutable bm25s index whose directory is named by its content hash."""

    def build(
        self, documents: tuple[SourceDocument, ...], artifact_root: Path
    ) -> ArtifactReference:
        artifact_root.mkdir(parents=True, exist_ok=True)
        ordered = sorted(documents, key=lambda document: document.external_id)
        texts = [f"{document.title}\n{document.text}" for document in ordered]
        corpus = [
            {
                "id": document.external_id,
                "title": document.title,
                "text": document.text,
            }
            for document in ordered
        ]

        bm25s: Any = importlib.import_module("bm25s")
        temporary_path = Path(tempfile.mkdtemp(prefix="bm25-", dir=artifact_root))
        try:
            tokens = bm25s.tokenize(texts, stopwords="en", show_progress=False)
            retriever = bm25s.BM25(corpus=corpus)
            retriever.index(tokens, show_progress=False)
            retriever.save(temporary_path, corpus=corpus, show_progress=False)
            content_hash = hash_directory(temporary_path)
            final_path = artifact_root / content_hash
            if final_path.exists():
                if hash_directory(final_path) != content_hash:
                    raise ValueError(f"corrupt content-addressed artifact: {final_path}")
            else:
                temporary_path.rename(final_path)
            return ArtifactReference(content_hash=content_hash, path=final_path)
        finally:
            if temporary_path.exists():
                shutil.rmtree(temporary_path)
