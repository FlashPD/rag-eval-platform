import asyncio
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from ragops.contracts import (
    AnswerResponse,
    CitationValidation,
    CitedAnswer,
    Confidence,
    GenerationOutcome,
    GenerationRequest,
    GenerationResult,
    Passage,
    TokenUsage,
)
from ragops.generation import (
    CitedAnswerer,
    GenerationFailure,
    GenerationProviderError,
    GenerationRefusalError,
    GenerationSchemaError,
    GenerationTimeoutError,
    VersionedAnswerPromptRenderer,
)
from ragops.protocols import Answerer

PROMPT_ROOT = Path(__file__).parents[2] / "prompts" / "answer"


def passage(local_id: str, rank: int) -> Passage:
    return Passage(
        local_id=local_id,
        document_id=f"doc-{local_id}",
        title=f"Title {local_id}",
        text=f"Evidence {local_id}",
        retrieval_rank=rank,
        retrieval_score=1.0 / rank,
    )


def result(output: CitedAnswer) -> GenerationResult:
    return GenerationResult(
        output=output,
        usage=TokenUsage(
            input_tokens=100,
            output_tokens=20,
            cached_input_tokens=75,
            cost_usd=Decimal("0.002"),
        ),
        provider="fake",
        model="fake-model",
        generator_configuration_hash="f" * 64,
        provider_request_id="provider-request-1",
    )


class FakeGenerator:
    provider = "fake"
    model = "fake-model"
    configuration_hash = "f" * 64

    def __init__(self, response: GenerationResult | BaseException) -> None:
        self.response = response
        self.requests: list[GenerationRequest] = []

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.requests.append(request)
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


def build_answerer(generator: FakeGenerator) -> CitedAnswerer:
    return CitedAnswerer(
        generator=generator,
        prompt_renderer=VersionedAnswerPromptRenderer(prompt_root=PROMPT_ROOT),
        trace_id_factory=lambda: "trace-1",
    )


def run_answer(
    generator: FakeGenerator,
    contexts: Sequence[Passage] = (passage("[1]", 1),),
) -> AnswerResponse:
    return asyncio.run(build_answerer(generator).answer("Question", contexts))


def test_valid_generation_returns_a_provenance_complete_answer() -> None:
    generator = FakeGenerator(
        result(
            CitedAnswer(
                answer="The evidence supports this [1].",
                citations=("[1]",),
                abstained=False,
                confidence=Confidence.HIGH,
            )
        )
    )
    answerer = build_answerer(generator)
    assert isinstance(answerer, Answerer)

    response = asyncio.run(answerer.answer("Question", (passage("[1]", 1),)))

    assert response.outcome == GenerationOutcome.OK
    assert response.citation_validation == CitationValidation(valid=True)
    assert response.provider == "fake"
    assert response.model == "fake-model"
    assert response.generator_configuration_hash == "f" * 64
    assert response.prompt_version == "answer-v1"
    assert len(response.rendered_prompt_hash) == 64
    assert response.provider_request_id == "provider-request-1"
    assert response.error is None
    assert generator.requests[0].trace_id == response.trace_id


def test_clean_abstention_has_a_distinct_outcome() -> None:
    response = run_answer(
        FakeGenerator(
            result(
                CitedAnswer(
                    answer="The supplied context is insufficient.",
                    citations=(),
                    abstained=True,
                    confidence=Confidence.LOW,
                )
            )
        )
    )

    assert response.outcome == GenerationOutcome.ABSTAINED
    assert response.abstained is True
    assert response.citation_validation == CitationValidation(valid=True)


def test_invalid_citation_is_preserved_and_classified_without_repair() -> None:
    response = run_answer(
        FakeGenerator(
            result(
                CitedAnswer(
                    answer="An unsupported citation [9].",
                    citations=("[9]",),
                    abstained=False,
                    confidence=Confidence.MEDIUM,
                )
            )
        )
    )

    assert response.outcome == GenerationOutcome.CITATION_ERROR
    assert response.citations == ("[9]",)
    assert response.citation_validation is not None
    assert response.citation_validation.unknown_citations == ("[9]",)


def test_response_contexts_follow_the_rank_order_used_in_the_prompt() -> None:
    response = run_answer(
        FakeGenerator(
            result(
                CitedAnswer(
                    answer="Second input, first-ranked evidence [1].",
                    citations=("[1]",),
                    abstained=False,
                    confidence=Confidence.HIGH,
                )
            )
        ),
        (passage("[2]", 2), passage("[1]", 1)),
    )

    assert [context.local_id for context in response.contexts] == ["[1]", "[2]"]


@pytest.mark.parametrize(
    ("failure", "expected_outcome"),
    [
        (GenerationSchemaError("invalid structured output"), GenerationOutcome.SCHEMA_ERROR),
        (GenerationRefusalError("provider refused"), GenerationOutcome.REFUSAL),
        (GenerationProviderError("provider unavailable"), GenerationOutcome.PROVIDER_ERROR),
        (GenerationTimeoutError("provider timed out"), GenerationOutcome.TIMEOUT),
    ],
)
def test_expected_generation_failures_become_typed_responses(
    failure: GenerationFailure,
    expected_outcome: GenerationOutcome,
) -> None:
    response = run_answer(FakeGenerator(failure))

    assert response.outcome == expected_outcome
    assert response.error == str(failure)
    assert response.citation_validation is None
    assert response.provider == "fake"
    assert response.model == "fake-model"
    assert response.usage == TokenUsage(input_tokens=0, output_tokens=0)


def test_failure_preserves_billable_usage_and_provider_request_id() -> None:
    usage = TokenUsage(
        input_tokens=50,
        output_tokens=5,
        cost_usd=Decimal("0.001"),
    )
    response = run_answer(
        FakeGenerator(
            GenerationSchemaError(
                "invalid structured output",
                usage=usage,
                provider_request_id="failed-request-1",
            )
        )
    )

    assert response.usage == usage
    assert response.provider_request_id == "failed-request-1"


@pytest.mark.parametrize(
    "failure",
    [
        lambda: GenerationProviderError(" "),
        lambda: GenerationProviderError("failure", provider_request_id=" "),
    ],
)
def test_handled_failures_require_usable_diagnostics(
    failure: Callable[[], GenerationProviderError],
) -> None:
    with pytest.raises(ValueError):
        failure()


def test_unexpected_generator_errors_are_not_hidden_as_provider_failures() -> None:
    with pytest.raises(RuntimeError, match="implementation bug"):
        run_answer(FakeGenerator(RuntimeError("implementation bug")))


def test_mismatched_result_provenance_is_rejected() -> None:
    mismatched = result(
        CitedAnswer(
            answer="Answer [1].",
            citations=("[1]",),
            abstained=False,
            confidence=Confidence.HIGH,
        )
    ).model_copy(update={"model": "unexpected-model"})

    with pytest.raises(ValueError, match="provenance does not match"):
        run_answer(FakeGenerator(mismatched))


def test_answer_response_rejects_an_outcome_that_hides_invalid_citations() -> None:
    with pytest.raises(ValidationError, match="ok outcome requires"):
        AnswerResponse(
            answer="Answer [9].",
            citations=("[9]",),
            abstained=False,
            confidence=Confidence.HIGH,
            contexts=(passage("[1]", 1),),
            usage=TokenUsage(input_tokens=1, output_tokens=1),
            outcome=GenerationOutcome.OK,
            trace_id="trace-1",
            provider="fake",
            model="fake-model",
            generator_configuration_hash="f" * 64,
            prompt_version="answer-v1",
            rendered_prompt_hash="a" * 64,
            citation_validation=CitationValidation(
                valid=False,
                unknown_citations=("[9]",),
            ),
        )
