import asyncio
from decimal import Decimal

import pytest
from pydantic import ValidationError

from ragops.contracts import (
    CitationValidation,
    CitedAnswer,
    Confidence,
    GenerationRequest,
    GenerationResult,
    Passage,
    TokenUsage,
)
from ragops.generation import validate_citations
from ragops.protocols import Generator


def passage(local_id: str) -> Passage:
    return Passage(
        local_id=local_id,
        document_id=f"doc-{local_id}",
        title="Title",
        text="Evidence",
        retrieval_rank=1,
        retrieval_score=0.9,
    )


class FakeGenerator:
    provider = "fake"
    model = "fake-model"
    configuration_hash = "f" * 64

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(
            output=CitedAnswer(
                answer="The supported answer [1].",
                citations=("[1]",),
                abstained=False,
                confidence=Confidence.HIGH,
            ),
            usage=TokenUsage(
                input_tokens=100,
                output_tokens=10,
                cached_input_tokens=80,
                cost_usd=Decimal("0.001"),
            ),
            provider="fake",
            model="fake-model",
            generator_configuration_hash=self.configuration_hash,
            provider_request_id=f"request-{request.trace_id}",
        )


def test_generator_protocol_normalizes_a_structured_result() -> None:
    generator = FakeGenerator()
    assert isinstance(generator, Generator)

    result = asyncio.run(
        generator.generate(
            GenerationRequest(
                system_prompt="Answer only from context.",
                user_prompt="Question and context",
                prompt_version="answer-v1",
                trace_id="trace-1",
            )
        )
    )

    assert result.output.citations == ("[1]",)
    assert result.provider == "fake"
    assert result.usage.cached_input_tokens == 80


def test_structured_answer_rejects_invalid_schema() -> None:
    with pytest.raises(ValidationError):
        CitedAnswer.model_validate(
            {
                "answer": "Answer",
                "citations": ["[1]"],
                "abstained": False,
                "confidence": "certain",
            }
        )

    with pytest.raises(ValidationError, match="answer cannot be blank"):
        CitedAnswer(
            answer="   ",
            citations=(),
            abstained=True,
            confidence=Confidence.LOW,
        )

    with pytest.raises(ValidationError, match="Extra inputs"):
        CitedAnswer.model_validate(
            {
                "answer": "Answer [1]",
                "citations": ["[1]"],
                "abstained": False,
                "confidence": "high",
                "unsupported_provider_field": True,
            }
        )


def test_token_usage_rejects_impossible_cache_accounting() -> None:
    with pytest.raises(ValidationError, match="cannot exceed input tokens"):
        TokenUsage(input_tokens=10, output_tokens=1, cached_input_tokens=11)


def test_citation_validation_contract_rejects_an_inconsistent_summary() -> None:
    with pytest.raises(ValidationError, match="must agree with reported errors"):
        CitationValidation(valid=True, unknown_citations=("[9]",))


def test_valid_citations_reference_unique_contexts_and_appear_inline() -> None:
    result = validate_citations(
        CitedAnswer(
            answer="Evidence supports the claim [1] and its consequence [2].",
            citations=("[1]", "[2]"),
            abstained=False,
            confidence=Confidence.HIGH,
        ),
        (passage("[1]"), passage("[2]")),
    )

    assert result == CitationValidation(valid=True)


def test_citation_validation_reports_model_errors_without_repairing_them() -> None:
    result = validate_citations(
        CitedAnswer(
            answer="An answer cites only the first passage [1].",
            citations=("[1]", "[1]", "[3]"),
            abstained=False,
            confidence=Confidence.MEDIUM,
        ),
        (passage("[1]"), passage("[2]")),
    )

    assert result.valid is False
    assert result.unknown_citations == ("[3]",)
    assert result.duplicate_citations == ("[1]",)
    assert result.missing_inline_citations == ("[3]",)


@pytest.mark.parametrize(
    ("answer", "expected_field"),
    [
        (
            CitedAnswer(
                answer="An uncited answer.",
                citations=(),
                abstained=False,
                confidence=Confidence.LOW,
            ),
            "missing_required_citation",
        ),
        (
            CitedAnswer(
                answer="I cannot answer from this context [1].",
                citations=("[1]",),
                abstained=True,
                confidence=Confidence.LOW,
            ),
            "citations_on_abstention",
        ),
    ],
)
def test_citation_validation_enforces_answer_abstention_consistency(
    answer: CitedAnswer,
    expected_field: str,
) -> None:
    result = validate_citations(answer, (passage("[1]"),))

    assert result.valid is False
    assert getattr(result, expected_field) is True


def test_clean_abstention_is_valid_without_citations() -> None:
    result = validate_citations(
        CitedAnswer(
            answer="The supplied context does not answer the question.",
            citations=(),
            abstained=True,
            confidence=Confidence.LOW,
        ),
        (passage("[1]"),),
    )

    assert result == CitationValidation(valid=True)


def test_duplicate_context_identifiers_are_rejected_as_ambiguous() -> None:
    answer = CitedAnswer(
        answer="Answer [1].",
        citations=("[1]",),
        abstained=False,
        confidence=Confidence.HIGH,
    )

    with pytest.raises(ValueError, match="context local IDs must be unique"):
        validate_citations(answer, (passage("[1]"), passage("[1]")))
