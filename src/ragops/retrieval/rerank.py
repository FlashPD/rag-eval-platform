"""Cross-encoder reranking interface and local adapter."""

import asyncio
import importlib
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol, cast

from ragops.contracts import PersistedDocument
from ragops.model_cache import configure_huggingface_cache


class Reranker(Protocol):
    model_id: str

    async def score(
        self, query: str, documents: Sequence[PersistedDocument]
    ) -> Sequence[float]: ...


class CrossEncoderReranker:
    def __init__(
        self,
        model_id: str,
        *,
        device: str | None = None,
        cache_directory: Path | None = None,
    ) -> None:
        self.model_id = model_id
        self._device = device
        self._cache_directory = cache_directory
        self._model: Any = None
        self._load_lock = threading.Lock()

    def _load(self) -> Any:
        with self._load_lock:
            if self._model is None:
                cache_directory = configure_huggingface_cache(self._cache_directory)
                module: Any = importlib.import_module("sentence_transformers")
                self._model = module.CrossEncoder(
                    self.model_id,
                    device=self._device,
                    cache_folder=cache_directory,
                )
            return self._model

    def _score(self, query: str, documents: Sequence[PersistedDocument]) -> Sequence[float]:
        model = self._load()
        pairs = [(query, f"{document.title}\n{document.text}") for document in documents]
        values = model.predict(pairs, show_progress_bar=False)
        return cast(list[float], values.tolist())

    async def score(self, query: str, documents: Sequence[PersistedDocument]) -> Sequence[float]:
        return await asyncio.to_thread(self._score, query, documents)
