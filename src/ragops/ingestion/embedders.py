"""Document embedding interfaces and sentence-transformers adapter."""

import asyncio
import importlib
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol, cast

from ragops.model_cache import configure_huggingface_cache


class DocumentEmbedder(Protocol):
    model_id: str
    dimension: int
    normalized: bool

    async def encode_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]: ...


class QueryEmbedder(Protocol):
    model_id: str
    dimension: int
    normalized: bool

    async def encode_query(self, text: str) -> Sequence[float]: ...


class SentenceTransformerEmbedder:
    dimension = 384

    def __init__(
        self,
        model_id: str,
        *,
        normalized: bool = True,
        batch_size: int = 32,
        device: str | None = None,
        cache_directory: Path | None = None,
    ) -> None:
        self.model_id = model_id
        self.normalized = normalized
        self._batch_size = batch_size
        self._device = device
        self._cache_directory = cache_directory
        self._model: Any = None
        self._load_lock = threading.Lock()

    def _load(self) -> Any:
        with self._load_lock:
            if self._model is None:
                cache_directory = configure_huggingface_cache(self._cache_directory)
                module: Any = importlib.import_module("sentence_transformers")
                self._model = module.SentenceTransformer(
                    self.model_id,
                    device=self._device,
                    cache_folder=cache_directory,
                )
            return self._model

    def _encode(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        model = self._load()
        encode = getattr(model, "encode_document", model.encode)
        values = encode(
            list(texts),
            batch_size=self._batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=self.normalized,
        )
        return cast(list[list[float]], values.tolist())

    def _encode_query(self, text: str) -> Sequence[float]:
        model = self._load()
        encode = getattr(model, "encode_query", model.encode)
        values = encode(
            text,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=self.normalized,
        )
        return cast(list[float], values.tolist())

    async def encode_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return await asyncio.to_thread(self._encode, texts)

    async def encode_query(self, text: str) -> Sequence[float]:
        return await asyncio.to_thread(self._encode_query, text)
