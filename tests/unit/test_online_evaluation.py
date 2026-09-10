import asyncio

from sqlalchemy import select

from ragops.contracts import (
    ONLINE_JUDGE_JOB_KIND,
    AnswerResponse,
    CitationValidation,
    Confidence,
    GenerationOutcome,
    Passage,
    TokenUsage,
)
from ragops.evaluation.online import OnlineEvaluationSampler, selected_for_online_evaluation
from ragops.persistence import Base, create_engine, create_session_factory
from ragops.persistence.models import JobRow


def answer(trace_id: str) -> AnswerResponse:
    return AnswerResponse(
        answer="Supported [1].",
        citations=("[1]",),
        abstained=False,
        confidence=Confidence.HIGH,
        contexts=(
            Passage(
                local_id="[1]",
                document_id="doc-1",
                title="Evidence",
                text="Supported.",
                retrieval_rank=1,
                retrieval_score=1,
            ),
        ),
        usage=TokenUsage(input_tokens=10, output_tokens=2),
        outcome=GenerationOutcome.OK,
        trace_id=trace_id,
        provider="openai",
        model="model",
        generator_configuration_hash="a" * 64,
        prompt_version="answer-v1",
        rendered_prompt_hash="b" * 64,
        citation_validation=CitationValidation(valid=True),
    )


def test_online_sampling_is_deterministic_and_honors_boundary_rates() -> None:
    assert selected_for_online_evaluation("trace", 0) is False
    assert selected_for_online_evaluation("trace", 1) is True
    assert selected_for_online_evaluation("trace", 0.25) == selected_for_online_evaluation(
        "trace", 0.25
    )


def test_selected_answer_is_enqueued_idempotently() -> None:
    async def exercise() -> None:
        engine = create_engine("sqlite+aiosqlite:///:memory:")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        sessions = create_session_factory(engine)
        sampler = OnlineEvaluationSampler(sessions, sample_rate=1)

        assert await sampler.submit(query="Question", answer=answer("trace-1")) is True
        assert await sampler.submit(query="Question", answer=answer("trace-1")) is True
        async with sessions() as session:
            rows = (await session.scalars(select(JobRow))).all()
        assert len(rows) == 1
        assert rows[0].kind == ONLINE_JUDGE_JOB_KIND
        await engine.dispose()

    asyncio.run(exercise())
