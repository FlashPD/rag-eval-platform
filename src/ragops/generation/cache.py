"""Content-addressed caching decorator for generation providers."""

import hashlib
import json

from ragops.contracts import GenerationRequest, GenerationResult, TokenUsage
from ragops.protocols import GenerationCache, Generator


def build_generation_cache_key(generator: Generator, request: GenerationRequest) -> str:
    """Key a response by model parameters and the exact semantic prompt."""

    canonical = json.dumps(
        {
            "generator_configuration_hash": generator.configuration_hash,
            "model": generator.model,
            "prompt_version": request.prompt_version,
            "provider": generator.provider,
            "rendered_prompt_hash": request.rendered_prompt_hash,
            "response_schema": request.response_schema,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class CachingGenerator:
    """Reuse immutable structured output while accounting for zero new spend."""

    def __init__(self, *, generator: Generator, cache: GenerationCache) -> None:
        self._generator = generator
        self._cache = cache
        self.provider = generator.provider
        self.model = generator.model
        self.configuration_hash = generator.configuration_hash

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        cache_key = build_generation_cache_key(self, request)
        cached = await self._cache.get(cache_key)
        if cached is not None:
            self._validate_provenance(cached, source="cached")
            return cached.model_copy(
                update={
                    "usage": TokenUsage(input_tokens=0, output_tokens=0),
                    "provider_request_id": None,
                    "cache_hit": True,
                }
            )

        result = await self._generator.generate(request)
        self._validate_provenance(result, source="generated")
        if result.cache_hit:
            raise ValueError("wrapped generator returned a result already marked as a cache hit")
        await self._cache.put(cache_key=cache_key, request=request, result=result)
        return result

    def _validate_provenance(self, result: GenerationResult, *, source: str) -> None:
        if (
            result.provider != self.provider
            or result.model != self.model
            or result.generator_configuration_hash != self.configuration_hash
        ):
            raise ValueError(f"{source} generation provenance does not match the cache key")
