"""Implementation-independent interfaces consumed by evaluation code."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from ragops.contracts import (
    AnswerResponse,
    GenerationRequest,
    GenerationResult,
    JudgeRequest,
    JudgeVerdict,
    Passage,
    RankedHit,
)


@runtime_checkable
class Retriever(Protocol):
    """Return ranked documents for a query."""

    async def retrieve(self, query: str, *, k: int) -> Sequence[RankedHit]: ...


@runtime_checkable
class Answerer(Protocol):
    """Produce a typed, cited answer from supplied context."""

    async def answer(self, query: str, contexts: Sequence[Passage]) -> AnswerResponse: ...


@runtime_checkable
class Generator(Protocol):
    """Send one rendered, schema-constrained prompt to any model provider."""

    provider: str
    model: str
    configuration_hash: str

    async def generate(self, request: GenerationRequest) -> GenerationResult: ...


@runtime_checkable
class GenerationCache(Protocol):
    """Store immutable normalized results under content-derived keys."""

    async def get(self, cache_key: str) -> GenerationResult | None: ...

    async def put(
        self,
        *,
        cache_key: str,
        request: GenerationRequest,
        result: GenerationResult,
    ) -> None: ...


@runtime_checkable
class Judge(Protocol):
    provider: str
    model: str
    configuration_hash: str
    prompt_version: str

    async def judge(self, request: JudgeRequest) -> JudgeVerdict: ...
