"""Implementation-independent interfaces consumed by evaluation code."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from ragops.contracts import AnswerResponse, Passage, RankedHit


@runtime_checkable
class Retriever(Protocol):
    """Return ranked documents for a query."""

    async def retrieve(self, query: str, *, k: int) -> Sequence[RankedHit]: ...


@runtime_checkable
class Answerer(Protocol):
    """Produce a typed, cited answer from supplied context."""

    async def answer(self, query: str, contexts: Sequence[Passage]) -> AnswerResponse: ...
