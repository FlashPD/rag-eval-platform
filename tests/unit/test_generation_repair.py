import asyncio
from decimal import Decimal

import pytest

from ragops.contracts import (
    CitedAnswer,
    Confidence,
    GenerationRequest,
    GenerationResult,
    TokenUsage,
)
from ragops.generation import GenerationSchemaError, RepairingGenerator


class SequencedGenerator:
    provider = "openai"
    model = "test-model"
    configuration_hash = "a" * 64

    def __init__(self, responses: list[GenerationResult | BaseException]) -> None:
        self.responses = responses
        self.requests: list[GenerationRequest] = []

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def request() -> GenerationRequest:
    return GenerationRequest(
        system_prompt="System",
        user_prompt="Question",
        prompt_version="answer-v1",
        trace_id="trace-1",
    )


def result() -> GenerationResult:
    return GenerationResult(
        output=CitedAnswer(
            answer="Supported [1].",
            citations=("[1]",),
            abstained=False,
            confidence=Confidence.HIGH,
        ),
        usage=TokenUsage(input_tokens=20, output_tokens=5, cost_usd=Decimal("0.02")),
        provider="openai",
        model="test-model",
        generator_configuration_hash="a" * 64,
    )


def test_schema_failure_gets_exactly_one_repair_attempt_and_combined_usage() -> None:
    delegate = SequencedGenerator(
        [
            GenerationSchemaError(
                "invalid",
                usage=TokenUsage(input_tokens=10, output_tokens=2, cost_usd=Decimal("0.01")),
            ),
            result(),
        ]
    )

    repaired = asyncio.run(RepairingGenerator(delegate).generate(request()))

    assert len(delegate.requests) == 2
    assert "repair_instruction" in delegate.requests[1].user_prompt
    assert repaired.usage.input_tokens == 30
    assert repaired.usage.output_tokens == 7
    assert repaired.usage.cost_usd == Decimal("0.03")


def test_second_schema_failure_is_returned_without_a_third_attempt() -> None:
    delegate = SequencedGenerator([GenerationSchemaError("first"), GenerationSchemaError("second")])

    with pytest.raises(GenerationSchemaError, match="second"):
        asyncio.run(RepairingGenerator(delegate).generate(request()))
    assert len(delegate.requests) == 2
