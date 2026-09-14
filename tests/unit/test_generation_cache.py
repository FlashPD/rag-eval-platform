import asyncio
from decimal import Decimal
from pathlib import Path

import pytest

from ragops.contracts import (
    AnswerResponse,
    CitedAnswer,
    Confidence,
    GenerationRequest,
    GenerationResult,
    Passage,
    TokenUsage,
)
from ragops.generation import (
    CachingGenerator,
    CitedAnswerer,
    GenerationProviderError,
    VersionedAnswerPromptRenderer,
    build_generation_cache_key,
)
from ragops.persistence import Base, SqlAlchemyGenerationCache, create_engine
from ragops.persistence.session import create_session_factory

PROMPT_ROOT = Path(__file__).parents[2] / "prompts" / "answer"


def request(*, trace_id: str = "trace-1", user_prompt: str = "Question") -> GenerationRequest:
    return GenerationRequest(
        system_prompt="Answer from context.",
        user_prompt=user_prompt,
        prompt_version="answer-v1",
        trace_id=trace_id,
    )


def result(*, answer: str = "Answer [1].") -> GenerationResult:
    return GenerationResult(
        output=CitedAnswer(
            answer=answer,
            citations=("[1]",),
            abstained=False,
            confidence=Confidence.HIGH,
        ),
        usage=TokenUsage(
            input_tokens=100,
            output_tokens=20,
            cached_input_tokens=50,
            cost_usd=Decimal("0.002"),
        ),
        provider="fake",
        model="fake-model",
        generator_configuration_hash="f" * 64,
        provider_request_id="provider-request-1",
    )


class MemoryGenerationCache:
    def __init__(self) -> None:
        self.values: dict[str, GenerationResult] = {}
        self.put_count = 0

    async def get(self, cache_key: str) -> GenerationResult | None:
        return self.values.get(cache_key)

    async def put(
        self,
        *,
        cache_key: str,
        request: GenerationRequest,
        result: GenerationResult,
    ) -> None:
        del request
        self.put_count += 1
        self.values.setdefault(cache_key, result)


class FakeGenerator:
    provider = "fake"
    model = "fake-model"
    configuration_hash = "f" * 64

    def __init__(self, responses: list[GenerationResult | BaseException]) -> None:
        self.responses = responses
        self.call_count = 0

    async def generate(self, generation_request: GenerationRequest) -> GenerationResult:
        del generation_request
        response = self.responses[self.call_count]
        self.call_count += 1
        if isinstance(response, BaseException):
            raise response
        return response


def test_cache_hit_reuses_output_without_reporting_new_usage_or_provider_request() -> None:
    async def exercise() -> None:
        delegate = FakeGenerator([result()])
        cache = MemoryGenerationCache()
        generator = CachingGenerator(generator=delegate, cache=cache)

        first = await generator.generate(request(trace_id="trace-1"))
        second = await generator.generate(request(trace_id="trace-2"))

        assert delegate.call_count == 1
        assert cache.put_count == 1
        assert first.cache_hit is False
        assert first.usage.cost_usd == Decimal("0.002")
        assert second.output == first.output
        assert second.cache_hit is True
        assert second.usage == TokenUsage(input_tokens=0, output_tokens=0)
        assert second.provider_request_id is None

    asyncio.run(exercise())


def test_cited_answerer_exposes_cache_hit_and_zero_incremental_cost() -> None:
    async def exercise() -> None:
        delegate = FakeGenerator([result()])
        generator = CachingGenerator(generator=delegate, cache=MemoryGenerationCache())
        answerer = CitedAnswerer(
            generator=generator,
            prompt_renderer=VersionedAnswerPromptRenderer(prompt_root=PROMPT_ROOT),
            trace_id_factory=iter(("trace-1", "trace-2")).__next__,
        )
        contexts = (
            Passage(
                local_id="[1]",
                document_id="doc-1",
                title="Title",
                text="Evidence",
                retrieval_rank=1,
                retrieval_score=0.9,
            ),
        )

        first: AnswerResponse = await answerer.answer("Question", contexts)
        second: AnswerResponse = await answerer.answer("Question", contexts)

        assert first.cache_hit is False
        assert first.usage.cost_usd == Decimal("0.002")
        assert second.cache_hit is True
        assert second.usage.cost_usd == 0
        assert delegate.call_count == 1

    asyncio.run(exercise())


def test_cache_key_ignores_trace_but_isolates_prompt_and_model_parameters() -> None:
    first_generator = FakeGenerator([])
    changed_generator = FakeGenerator([])
    changed_generator.configuration_hash = "a" * 64

    first = build_generation_cache_key(first_generator, request(trace_id="trace-1"))
    retried = build_generation_cache_key(first_generator, request(trace_id="trace-2"))
    changed_prompt = build_generation_cache_key(
        first_generator,
        request(trace_id="trace-1", user_prompt="Different question"),
    )
    changed_parameters = build_generation_cache_key(
        changed_generator,
        request(trace_id="trace-1"),
    )

    assert first == retried
    assert len({first, changed_prompt, changed_parameters}) == 3


def test_expected_provider_failure_is_not_cached() -> None:
    async def exercise() -> None:
        delegate = FakeGenerator([GenerationProviderError("temporary failure"), result()])
        cache = MemoryGenerationCache()
        generator = CachingGenerator(generator=delegate, cache=cache)

        with pytest.raises(GenerationProviderError, match="temporary failure"):
            await generator.generate(request())
        recovered = await generator.generate(request())

        assert recovered.cache_hit is False
        assert delegate.call_count == 2
        assert cache.put_count == 1

    asyncio.run(exercise())


def test_cached_provenance_mismatch_is_rejected() -> None:
    async def exercise() -> None:
        delegate = FakeGenerator([])
        cache = MemoryGenerationCache()
        generation_request = request()
        key = build_generation_cache_key(delegate, generation_request)
        cache.values[key] = result().model_copy(update={"model": "wrong-model"})
        generator = CachingGenerator(generator=delegate, cache=cache)

        with pytest.raises(ValueError, match="cached generation provenance"):
            await generator.generate(generation_request)

    asyncio.run(exercise())


def test_sqlalchemy_cache_round_trips_and_never_overwrites() -> None:
    async def exercise() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        cache = SqlAlchemyGenerationCache(create_session_factory(engine))
        generation_request = request()
        delegate = FakeGenerator([])
        key = build_generation_cache_key(delegate, generation_request)

        await cache.put(cache_key=key, request=generation_request, result=result())
        await cache.put(
            cache_key=key,
            request=generation_request,
            result=result(answer="A later answer [1]."),
        )

        loaded = await cache.get(key)
        assert loaded == result()
        assert await cache.count() == 1
        await engine.dispose()

    asyncio.run(exercise())


def test_sqlalchemy_cache_rejects_reinserting_a_cache_hit() -> None:
    async def exercise() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        cache = SqlAlchemyGenerationCache(create_session_factory(engine))

        with pytest.raises(ValueError, match="already marked as a cache hit"):
            await cache.put(
                cache_key="a" * 64,
                request=request(),
                result=result().model_copy(update={"cache_hit": True}),
            )
        await engine.dispose()

    asyncio.run(exercise())


def test_sqlalchemy_cache_rejects_malformed_keys() -> None:
    async def exercise() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        cache = SqlAlchemyGenerationCache(create_session_factory(engine))

        with pytest.raises(ValueError, match="64-character lowercase hex"):
            await cache.get("not-a-cache-key")
        await engine.dispose()

    asyncio.run(exercise())
