import asyncio
import json
from decimal import Decimal

import httpx2
import pytest
from openai import AsyncOpenAI

from ragops.config import LLMProfile, ModelPricing, PricingTable
from ragops.contracts import Confidence, GenerationRequest
from ragops.generation import (
    GenerationProviderError,
    GenerationRefusalError,
    GenerationSchemaError,
    OpenAIGenerator,
)

PROFILE = LLMProfile(
    provider="openai",
    model="gpt-test",
    effort="medium",
    max_tokens=1_024,
)
PRICING = PricingTable(
    providers={
        "openai": {
            "gpt-test": ModelPricing(
                input_per_million_tokens=Decimal("1"),
                cached_input_per_million_tokens=Decimal("0.1"),
                cache_write_input_per_million_tokens=Decimal("1.25"),
                output_per_million_tokens=Decimal("10"),
            )
        }
    }
)
REQUEST = GenerationRequest(
    system_prompt="Answer from supplied evidence.",
    user_prompt="<question>What is supported?</question>",
    prompt_version="answer-v1",
    trace_id="trace-1",
)


def response_body(
    *,
    content: list[dict[str, object]] | None = None,
    status: str = "completed",
) -> dict[str, object]:
    answer = {
        "answer": "The evidence supports it [1].",
        "citations": ["[1]"],
        "abstained": False,
        "confidence": "high",
    }
    return {
        "id": "resp_123",
        "object": "response",
        "created_at": 1_750_000_000,
        "status": status,
        "error": None,
        "incomplete_details": ({"reason": "max_output_tokens"} if status == "incomplete" else None),
        "instructions": "Answer from supplied evidence.",
        "model": "gpt-test",
        "output": [
            {
                "id": "msg_123",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": content
                or [
                    {
                        "type": "output_text",
                        "text": json.dumps(answer),
                        "annotations": [],
                        "logprobs": [],
                    }
                ],
            }
        ],
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": 100,
            "input_tokens_details": {"cached_tokens": 60, "cache_write_tokens": 10},
            "output_tokens": 20,
            "output_tokens_details": {"reasoning_tokens": 5},
            "total_tokens": 120,
        },
    }


def generator_for(handler: httpx2.MockTransport) -> OpenAIGenerator:
    client = AsyncOpenAI(
        api_key="test-key",
        base_url="https://example.test/v1",
        http_client=httpx2.AsyncClient(transport=handler),
        max_retries=0,
    )
    return OpenAIGenerator(profile=PROFILE, pricing=PRICING, client=client)


def test_openai_adapter_sends_structured_response_request_and_accounts_for_cost() -> None:
    captured: dict[str, object] = {}

    async def handle(request: httpx2.Request) -> httpx2.Response:
        captured.update(json.loads(request.content))
        return httpx2.Response(200, json=response_body())

    result = asyncio.run(generator_for(httpx2.MockTransport(handle)).generate(REQUEST))

    assert captured["model"] == "gpt-test"
    assert captured["instructions"] == REQUEST.system_prompt
    assert captured["input"] == REQUEST.user_prompt
    assert captured["store"] is False
    assert captured["prompt_cache_key"] == REQUEST.rendered_prompt_hash
    assert captured["reasoning"] == {"effort": "medium"}
    assert captured["text"]["format"]["type"] == "json_schema"  # type: ignore[index]
    assert result.output.confidence is Confidence.HIGH
    assert result.provider_request_id == "resp_123"
    assert result.usage.cached_input_tokens == 60
    assert result.usage.cache_write_input_tokens == 10
    assert result.usage.cost_usd == Decimal("0.0002485")


def test_openai_adapter_maps_refusals_with_billable_usage() -> None:
    async def handle(request: httpx2.Request) -> httpx2.Response:
        del request
        return httpx2.Response(
            200,
            json=response_body(content=[{"type": "refusal", "refusal": "Cannot comply."}]),
        )

    with pytest.raises(GenerationRefusalError) as raised:
        asyncio.run(generator_for(httpx2.MockTransport(handle)).generate(REQUEST))

    assert raised.value.provider_request_id == "resp_123"
    assert raised.value.usage.input_tokens == 100


def test_openai_adapter_maps_incomplete_structured_output() -> None:
    async def handle(request: httpx2.Request) -> httpx2.Response:
        del request
        return httpx2.Response(200, json=response_body(status="incomplete"))

    with pytest.raises(GenerationSchemaError, match="max_output_tokens"):
        asyncio.run(generator_for(httpx2.MockTransport(handle)).generate(REQUEST))


def test_openai_adapter_maps_provider_errors_without_leaking_credentials() -> None:
    async def handle(request: httpx2.Request) -> httpx2.Response:
        del request
        return httpx2.Response(
            429,
            headers={"x-request-id": "req_failed"},
            json={"error": {"message": "rate limited", "type": "rate_limit_error"}},
        )

    with pytest.raises(GenerationProviderError) as raised:
        asyncio.run(generator_for(httpx2.MockTransport(handle)).generate(REQUEST))

    assert raised.value.provider_request_id == "req_failed"
    assert "test-key" not in str(raised.value)
