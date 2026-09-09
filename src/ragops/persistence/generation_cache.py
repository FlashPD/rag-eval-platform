"""SQLAlchemy persistence for immutable generation results."""

import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ragops.contracts import GenerationRequest, GenerationResult
from ragops.persistence.models import GenerationCacheRow

CACHE_KEY_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def _validate_cache_key(cache_key: str) -> None:
    if CACHE_KEY_PATTERN.fullmatch(cache_key) is None:
        raise ValueError("generation cache key must be a 64-character lowercase hex digest")


class SqlAlchemyGenerationCache:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, cache_key: str) -> GenerationResult | None:
        _validate_cache_key(cache_key)
        async with self._sessions() as session:
            row = await session.get(GenerationCacheRow, cache_key)
        return GenerationResult.model_validate(row.result) if row is not None else None

    async def put(
        self,
        *,
        cache_key: str,
        request: GenerationRequest,
        result: GenerationResult,
    ) -> None:
        _validate_cache_key(cache_key)
        if result.cache_hit:
            raise ValueError("cannot persist a generation result already marked as a cache hit")
        values = {
            "cache_key": cache_key,
            "provider": result.provider,
            "model_id": result.model,
            "generator_configuration_hash": result.generator_configuration_hash,
            "prompt_version": request.prompt_version,
            "rendered_prompt_hash": request.rendered_prompt_hash,
            "response_schema": request.response_schema,
            "result": result.model_dump(mode="json"),
        }
        async with self._sessions.begin() as session:
            bind = session.get_bind()
            statement: Any
            if bind.dialect.name == "postgresql":
                statement = postgresql_insert(GenerationCacheRow).values(**values)
            elif bind.dialect.name == "sqlite":
                statement = sqlite_insert(GenerationCacheRow).values(**values)
            else:
                raise RuntimeError(f"unsupported database dialect: {bind.dialect.name}")
            await session.execute(statement.on_conflict_do_nothing(index_elements=["cache_key"]))

    async def count(self) -> int:
        async with self._sessions() as session:
            statement = select(func.count()).select_from(GenerationCacheRow)
            return int(await session.scalar(statement) or 0)
