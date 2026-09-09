"""Construct configured, cached OpenAI judges."""

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ragops.config import ConfigBundle, Settings
from ragops.evaluation.judging import CachingJudge, OpenAIJudge, VersionedJudgePromptRenderer
from ragops.persistence import SqlAlchemyJudgeCache
from ragops.protocols import Judge


def build_judges(
    bundle: ConfigBundle,
    sessions: async_sessionmaker[AsyncSession],
    *,
    settings: Settings,
    prompt_version: str = "judge-v1",
) -> tuple[VersionedJudgePromptRenderer, dict[str, Judge]]:
    if settings.openai_api_key is None:
        raise ValueError("RAGOPS_OPENAI_API_KEY is required for judging")
    renderer = VersionedJudgePromptRenderer(
        prompt_root=Path(settings.prompt_directory) / "judge",
        version=prompt_version,
    )
    cache = SqlAlchemyJudgeCache(sessions)
    judges: dict[str, Judge] = {}
    for name, profile in bundle.models.judges.items():
        if profile.provider != "openai":
            continue
        judges[name] = CachingJudge(
            judge=OpenAIJudge(
                profile=profile,
                pricing=bundle.pricing,
                prompt_version=prompt_version,
                api_key=settings.openai_api_key.get_secret_value(),
                timeout_seconds=settings.generation_timeout_seconds,
            ),
            cache=cache,
        )
    if not judges:
        raise ValueError("no OpenAI judge profiles are configured")
    return renderer, judges
