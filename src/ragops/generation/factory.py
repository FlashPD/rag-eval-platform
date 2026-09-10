"""Configuration-driven construction of the cited answer pipeline."""

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ragops.config import ConfigBundle, Settings
from ragops.evaluation.online import OnlineEvaluationSampler
from ragops.generation.cache import CachingGenerator
from ragops.generation.openai import OpenAIGenerator
from ragops.generation.prompting import VersionedAnswerPromptRenderer
from ragops.generation.repair import RepairingGenerator
from ragops.generation.service import (
    CitedAnswerer,
    DatasetRoutingAnswerService,
    RetrievalCitedAnswerService,
)
from ragops.persistence.generation_cache import SqlAlchemyGenerationCache
from ragops.retrieval.pipeline import SearchExecutor


def build_answer_service(
    bundle: ConfigBundle,
    sessions: async_sessionmaker[AsyncSession],
    *,
    search: SearchExecutor,
    settings: Settings,
    prompt_version: str = "answer-v1",
    enable_online_sampling: bool = True,
) -> RetrievalCitedAnswerService:
    """Wire retrieval, OpenAI, repair, durable caching, and citation validation."""
    api_key = settings.openai_api_key
    if api_key is None:
        raise ValueError("RAGOPS_OPENAI_API_KEY is required for answer generation")

    answerers: dict[str, CitedAnswerer] = {}
    for profile_name, profile in bundle.models.generators.items():
        if profile.provider != "openai":
            continue
        generator = CachingGenerator(
            generator=RepairingGenerator(
                OpenAIGenerator(
                    profile=profile,
                    pricing=bundle.pricing,
                    api_key=api_key.get_secret_value(),
                    timeout_seconds=settings.generation_timeout_seconds,
                )
            ),
            cache=SqlAlchemyGenerationCache(sessions),
        )
        answerers[profile_name] = CitedAnswerer(
            generator=generator,
            prompt_renderer=VersionedAnswerPromptRenderer(
                prompt_root=Path(settings.prompt_directory) / "answer",
                version=prompt_version,
            ),
        )
    if not answerers:
        raise ValueError("no OpenAI generator profiles are configured")
    return RetrievalCitedAnswerService(
        search=search,
        answerers=answerers,
        prompt_version=prompt_version,
        context_count=settings.answer_context_count,
        online_sampler=(
            OnlineEvaluationSampler(
                sessions,
                sample_rate=settings.online_evaluation_sample_rate,
            )
            if enable_online_sampling
            else None
        ),
    )


def build_evaluation_answer_service(
    bundle: ConfigBundle,
    sessions: async_sessionmaker[AsyncSession],
    *,
    search: SearchExecutor,
    settings: Settings,
) -> DatasetRoutingAnswerService:
    """Route SciFact claims to its verification schema and other datasets to QA."""
    default = build_answer_service(
        bundle,
        sessions,
        search=search,
        settings=settings,
        prompt_version="answer-v1",
        enable_online_sampling=False,
    )
    scifact = build_answer_service(
        bundle,
        sessions,
        search=search,
        settings=settings,
        prompt_version="scifact-v1",
        enable_online_sampling=False,
    )
    return DatasetRoutingAnswerService(
        default=default,
        by_dataset={"scifact": scifact},
        by_prompt_version={"answer-v1": default, "scifact-v1": scifact},
    )
