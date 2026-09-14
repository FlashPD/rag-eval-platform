"""Expected provider failures normalized by the generation boundary."""

from typing import ClassVar

from ragops.contracts import GenerationOutcome, TokenUsage


class GenerationFailure(RuntimeError):
    """A handled generation failure with any billable usage preserved."""

    outcome: ClassVar[GenerationOutcome]

    def __init__(
        self,
        message: str,
        *,
        usage: TokenUsage | None = None,
        provider_request_id: str | None = None,
    ) -> None:
        if not message.strip():
            raise ValueError("generation failure message cannot be blank")
        if provider_request_id is not None and not provider_request_id.strip():
            raise ValueError("provider request ID cannot be blank")
        super().__init__(message)
        self.usage = usage or TokenUsage(input_tokens=0, output_tokens=0)
        self.provider_request_id = provider_request_id


class GenerationSchemaError(GenerationFailure):
    outcome = GenerationOutcome.SCHEMA_ERROR


class GenerationRefusalError(GenerationFailure):
    outcome = GenerationOutcome.REFUSAL


class GenerationProviderError(GenerationFailure):
    outcome = GenerationOutcome.PROVIDER_ERROR


class GenerationTimeoutError(GenerationFailure):
    outcome = GenerationOutcome.TIMEOUT
