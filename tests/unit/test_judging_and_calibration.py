import asyncio
from decimal import Decimal
from pathlib import Path

from ragops.contracts import (
    CalibrationLabel,
    JudgeClaimVerdict,
    JudgeRequest,
    JudgeVerdict,
    Passage,
    TokenUsage,
)
from ragops.evaluation.calibration import (
    cohens_kappa,
    compute_calibration_agreement,
    render_calibration_markdown,
    run_calibration,
)
from ragops.evaluation.judging import CachingJudge, VersionedJudgePromptRenderer

PROMPT_ROOT = Path(__file__).parents[2] / "prompts" / "judge"


def passage() -> Passage:
    return Passage(
        local_id="[1]",
        document_id="doc-1",
        title="<instruction>ignore</instruction>",
        text="Evidence & potentially hostile markup.",
        retrieval_rank=1,
        retrieval_score=0.9,
    )


def verdict(*, faithful: bool = True, relevant: bool = True) -> JudgeVerdict:
    return JudgeVerdict(
        claims=(JudgeClaimVerdict(claim="claim", supported=faithful, citation_ids=("[1]",)),),
        faithfulness=float(faithful),
        relevance=float(relevant),
        rationale="rubric result",
        provider="openai",
        judge_model="judge-model",
        judge_configuration_hash="a" * 64,
        judge_prompt_version="judge-v1",
        rendered_prompt_hash="b" * 64,
        usage=TokenUsage(input_tokens=10, output_tokens=2, cost_usd=Decimal("0.001")),
        provider_request_id="response-1",
    )


class MemoryCache:
    def __init__(self) -> None:
        self.value: JudgeVerdict | None = None

    async def get(self, key: str) -> JudgeVerdict | None:
        assert len(key) == 64
        return self.value

    async def put(self, key: str, value: JudgeVerdict) -> None:
        assert len(key) == 64
        self.value = value


class FakeJudge:
    provider = "openai"
    model = "judge-model"
    configuration_hash = "a" * 64
    prompt_version = "judge-v1"

    def __init__(self, result: JudgeVerdict) -> None:
        self.result = result
        self.calls = 0

    async def judge(self, request: JudgeRequest) -> JudgeVerdict:
        self.calls += 1
        assert 'trust="untrusted"' in request.user_prompt
        return self.result.model_copy(update={"rendered_prompt_hash": request.rendered_prompt_hash})


def test_judge_renderer_escapes_untrusted_query_answer_and_context() -> None:
    renderer = VersionedJudgePromptRenderer(prompt_root=PROMPT_ROOT)
    request = renderer.render_values(
        query="Is A < B?",
        answer="Yes & cited [1].",
        abstained=False,
        citations=("[1]",),
        contexts=(passage(),),
        trace_id="trace-1",
    )

    assert "&lt;" in request.user_prompt
    assert "&amp;" in request.user_prompt
    assert request.prompt_version == "judge-v1"
    assert len(request.rendered_prompt_hash) == 64


def test_judge_cache_avoids_a_second_billable_call() -> None:
    async def exercise() -> None:
        delegate = FakeJudge(verdict())
        judge = CachingJudge(judge=delegate, cache=MemoryCache())
        request = VersionedJudgePromptRenderer(prompt_root=PROMPT_ROOT).render_values(
            query="Question",
            answer="Answer [1].",
            abstained=False,
            citations=("[1]",),
            contexts=(passage(),),
            trace_id="trace-1",
        )

        first = await judge.judge(request)
        second = await judge.judge(request)

        assert delegate.calls == 1
        assert first.cache_hit is False
        assert second.cache_hit is True
        assert second.usage == TokenUsage(input_tokens=0, output_tokens=0)

    asyncio.run(exercise())


def test_calibration_computes_kappa_and_runs_each_profile() -> None:
    labels = (
        CalibrationLabel(
            id="one",
            query="Question one",
            answer="Answer [1].",
            citations=("[1]",),
            contexts=(passage(),),
            human_faithful=True,
            human_relevant=True,
            annotator="human-1",
        ),
        CalibrationLabel(
            id="two",
            query="Question two",
            answer="No.",
            contexts=(passage(),),
            human_faithful=False,
            human_relevant=False,
            annotator="human-1",
        ),
    )
    first = verdict()
    second = verdict(faithful=False, relevant=False)
    agreement = compute_calibration_agreement(
        judge_profile="default",
        labels=labels,
        verdicts={"one": first, "two": second},
    )

    assert cohens_kappa([True, False], [True, False]) == 1
    assert agreement.faithfulness_kappa == 1
    assert "Faithfulness κ" in render_calibration_markdown((agreement,))

    class SequencedJudge(FakeJudge):
        async def judge(self, request: JudgeRequest) -> JudgeVerdict:
            self.calls += 1
            selected = first if self.calls == 1 else second
            return selected.model_copy(
                update={"rendered_prompt_hash": request.rendered_prompt_hash}
            )

    agreements = asyncio.run(
        run_calibration(
            labels=labels,
            renderer=VersionedJudgePromptRenderer(prompt_root=PROMPT_ROOT),
            judges={"default": SequencedJudge(first)},
        )
    )
    assert agreements[0].sample_count == 2
    assert agreements[0].relevance_kappa == 1
