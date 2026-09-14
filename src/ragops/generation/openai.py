"""OpenAI Responses API adapter for schema-constrained generation."""

from __future__ import annotations

import openai
from openai import AsyncOpenAI
from openai.types.responses import ParsedResponse
from pydantic import Field, ValidationError

from ragops.config import LLMProfile, PricingTable
from ragops.contracts import (
    CitedAnswer,
    Confidence,
    GenerationRequest,
    GenerationResult,
    SciFactLabel,
    TokenUsage,
)
from ragops.contracts.base import Contract
from ragops.generation.errors import (
    GenerationProviderError,
    GenerationRefusalError,
    GenerationSchemaError,
    GenerationTimeoutError,
)


class RationaleSentenceSelection(Contract):
    """Schema-safe rationale entry used at the OpenAI boundary."""

    local_id: str = Field(min_length=1)
    sentence_indices: tuple[int, ...] = ()


class OpenAICitedAnswer(Contract):
    """Structured-output DTO without a free-form JSON object map.

    OpenAI strict structured outputs do not accept the arbitrary-key object emitted
    by ``dict[str, tuple[int, ...]]``. The provider returns a list of typed entries,
    which is normalized back into the provider-neutral ``CitedAnswer`` contract.
    """

    answer: str = Field(min_length=1, max_length=32_768)
    citations: tuple[str, ...] = ()
    abstained: bool
    confidence: Confidence
    verification_label: SciFactLabel | None = None
    rationale_sentences: tuple[RationaleSentenceSelection, ...] = ()


class OpenAIGenerator:
    """Generate typed answers with the Responses API and preserve provider accounting."""

    provider = "openai"

    def __init__(
        self,
        *,
        profile: LLMProfile,
        pricing: PricingTable,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        client: AsyncOpenAI | None = None,
    ) -> None:
        if profile.provider != self.provider:
            raise ValueError(f"OpenAIGenerator cannot use provider {profile.provider!r}")
        if timeout_seconds <= 0:
            raise ValueError("generation timeout must be positive")
        self._profile = profile
        self._pricing = pricing
        self._client = client or AsyncOpenAI(api_key=api_key, timeout=timeout_seconds)
        self._timeout_seconds = timeout_seconds
        self.model = profile.model
        self.configuration_hash = profile.configuration_hash

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        """Call OpenAI once and normalize structured output, failures, and token cost."""
        try:
            response = await self._client.responses.parse(
                model=self.model,
                instructions=request.system_prompt,
                input=request.user_prompt,
                max_output_tokens=self._profile.max_tokens,
                text_format=OpenAICitedAnswer,
                reasoning=(
                    {"effort": self._profile.effort}
                    if self._profile.effort is not None
                    else openai.omit
                ),
                temperature=(
                    self._profile.temperature
                    if self._profile.temperature is not None
                    else openai.omit
                ),
                prompt_cache_key=request.rendered_prompt_hash[:64],
                store=False,
                timeout=self._timeout_seconds,
            )
        except openai.APITimeoutError as error:
            raise GenerationTimeoutError("OpenAI generation timed out") from error
        except (openai.APIConnectionError, openai.APIStatusError) as error:
            request_id = getattr(error, "request_id", None)
            raise GenerationProviderError(
                f"OpenAI generation failed: {error}",
                provider_request_id=request_id,
            ) from error
        except ValidationError as error:
            raise GenerationSchemaError(
                f"OpenAI returned invalid structured output: {error}"
            ) from error

        parsed_response = response
        usage = self._usage(parsed_response)
        refusal = self._refusal(parsed_response)
        if refusal is not None:
            raise GenerationRefusalError(
                refusal,
                usage=usage,
                provider_request_id=parsed_response.id,
            )
        if parsed_response.status != "completed":
            reason = (
                parsed_response.incomplete_details.reason
                if parsed_response.incomplete_details is not None
                else parsed_response.status
            )
            raise GenerationSchemaError(
                f"OpenAI response was not complete: {reason}",
                usage=usage,
                provider_request_id=parsed_response.id,
            )
        if parsed_response.output_parsed is None:
            raise GenerationSchemaError(
                "OpenAI response did not contain a parsed cited answer",
                usage=usage,
                provider_request_id=parsed_response.id,
            )
        rationale_sentences: dict[str, tuple[int, ...]] = {}
        for selection in parsed_response.output_parsed.rationale_sentences:
            if selection.local_id in rationale_sentences:
                raise GenerationSchemaError(
                    f"OpenAI returned duplicate rationale local ID: {selection.local_id}",
                    usage=usage,
                    provider_request_id=parsed_response.id,
                )
            rationale_sentences[selection.local_id] = selection.sentence_indices
        normalized = CitedAnswer(
            answer=parsed_response.output_parsed.answer,
            citations=parsed_response.output_parsed.citations,
            abstained=parsed_response.output_parsed.abstained,
            confidence=parsed_response.output_parsed.confidence,
            verification_label=parsed_response.output_parsed.verification_label,
            rationale_sentences=rationale_sentences,
        )
        return GenerationResult(
            output=normalized,
            usage=usage,
            provider=self.provider,
            model=self.model,
            generator_configuration_hash=self.configuration_hash,
            provider_request_id=parsed_response.id,
        )

    def _usage(self, response: ParsedResponse[OpenAICitedAnswer]) -> TokenUsage:
        if response.usage is None:
            return TokenUsage(input_tokens=0, output_tokens=0)
        cached = response.usage.input_tokens_details.cached_tokens
        cache_write = response.usage.input_tokens_details.cache_write_tokens
        cost = self._pricing.calculate_cost(
            provider=self.provider,
            model=self.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cached_input_tokens=cached,
            cache_write_input_tokens=cache_write,
        )
        return TokenUsage(
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            cached_input_tokens=cached,
            cache_write_input_tokens=cache_write,
            cost_usd=cost,
        )

    @staticmethod
    def _refusal(response: ParsedResponse[OpenAICitedAnswer]) -> str | None:
        for item in response.output:
            if item.type != "message":
                continue
            for content in item.content:
                if content.type == "refusal":
                    return content.refusal or "OpenAI refused the generation request"
        return None
