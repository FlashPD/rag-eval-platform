"""Cross-encoder reranking interface and local adapter."""

import asyncio
import importlib
import threading
from collections.abc import Sequence
from typing import Any, Protocol, cast

from ragops.contracts import PersistedDocument


class Reranker(Protocol):
    model_id: str

    async def score(
        self, query: str, documents: Sequence[PersistedDocument]
    ) -> Sequence[float]: ...


class CrossEncoderReranker:
    def __init__(self, model_id: str, *, device: str | None = None) -> None:
        self.model_id = model_id
        self._device = device
        self._model: Any = None
        self._load_lock = threading.Lock()

    def _load(self) -> Any:
        with self._load_lock:
            if self._model is None:
                module: Any = importlib.import_module("sentence_transformers")
                self._model = module.CrossEncoder(self.model_id, device=self._device)
            return self._model

    def _score(self, query: str, documents: Sequence[PersistedDocument]) -> Sequence[float]:
        model = self._load()
        pairs = [(query, f"{document.title}\n{document.text}") for document in documents]
        values = model.predict(pairs, show_progress_bar=False)
        return cast(list[float], values.tolist())

    async def score(self, query: str, documents: Sequence[PersistedDocument]) -> Sequence[float]:
        return await asyncio.to_thread(self._score, query, documents)
