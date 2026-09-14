"""Single-attempt structured-output repair at the provider boundary."""

from ragops.contracts import GenerationRequest, GenerationResult, TokenUsage
from ragops.generation.errors import GenerationFailure, GenerationSchemaError
from ragops.protocols import Generator


def _combined_usage(first: TokenUsage, second: TokenUsage) -> TokenUsage:
    return TokenUsage(
        input_tokens=first.input_tokens + second.input_tokens,
        output_tokens=first.output_tokens + second.output_tokens,
        cached_input_tokens=first.cached_input_tokens + second.cached_input_tokens,
        cache_write_input_tokens=(first.cache_write_input_tokens + second.cache_write_input_tokens),
        cost_usd=first.cost_usd + second.cost_usd,
    )


class RepairingGenerator:
    """Retry one schema failure with an explicit schema-compliance instruction."""

    def __init__(self, generator: Generator) -> None:
        self._generator = generator
        self.provider = generator.provider
        self.model = generator.model
        self.configuration_hash = generator.configuration_hash

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        try:
            return await self._generator.generate(request)
        except GenerationSchemaError as first_error:
            repair_request = request.model_copy(
                update={
                    "user_prompt": request.user_prompt
                    + "\n\n<repair_instruction>Return one complete value matching the requested "
                    "schema. Do not add prose outside it.</repair_instruction>"
                }
            )
            try:
                repaired = await self._generator.generate(repair_request)
            except GenerationFailure as second_error:
                second_error.usage = _combined_usage(first_error.usage, second_error.usage)
                raise
            return repaired.model_copy(
                update={"usage": _combined_usage(first_error.usage, repaired.usage)}
            )
