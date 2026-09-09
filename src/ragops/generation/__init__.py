"""Provider-neutral answer generation building blocks."""

from ragops.generation.cache import CachingGenerator, build_generation_cache_key
from ragops.generation.errors import (
    GenerationFailure,
    GenerationProviderError,
    GenerationRefusalError,
    GenerationSchemaError,
    GenerationTimeoutError,
)
from ragops.generation.openai import OpenAIGenerator
from ragops.generation.prompting import VersionedAnswerPromptRenderer
from ragops.generation.repair import RepairingGenerator
from ragops.generation.service import (
    AnswerService,
    CitedAnswerer,
    DatasetRoutingAnswerService,
    RetrievalCitedAnswerService,
)
from ragops.generation.validation import validate_citations

__all__ = [
    "AnswerService",
    "CachingGenerator",
    "CitedAnswerer",
    "DatasetRoutingAnswerService",
    "GenerationFailure",
    "GenerationProviderError",
    "GenerationRefusalError",
    "GenerationSchemaError",
    "GenerationTimeoutError",
    "OpenAIGenerator",
    "RepairingGenerator",
    "RetrievalCitedAnswerService",
    "VersionedAnswerPromptRenderer",
    "build_generation_cache_key",
    "validate_citations",
]
