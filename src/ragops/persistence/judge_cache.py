"""Immutable SQLAlchemy-backed judge response cache."""

import re
from typing import Any

from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ragops.contracts import JudgeVerdict
from ragops.persistence.models import JudgeCacheRow

_KEY = re.compile(r"^[a-f0-9]{64}$")


class SqlAlchemyJudgeCache:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def get(self, key: str) -> JudgeVerdict | None:
        self._validate(key)
        async with self._sessions() as session:
            row = await session.get(JudgeCacheRow, key)
        return JudgeVerdict.model_validate(row.result) if row is not None else None

    async def put(self, key: str, verdict: JudgeVerdict) -> None:
        self._validate(key)
        if verdict.cache_hit:
            raise ValueError("cannot persist a cached judge verdict")
        values = {
            "cache_key": key,
            "provider": verdict.provider,
            "model_id": verdict.judge_model,
            "judge_configuration_hash": verdict.judge_configuration_hash,
            "prompt_version": verdict.judge_prompt_version,
            "rendered_prompt_hash": verdict.rendered_prompt_hash,
            "result": verdict.model_dump(mode="json"),
        }
        async with self._sessions.begin() as session:
            dialect = session.get_bind().dialect.name
            statement: Any
            if dialect == "postgresql":
                statement = postgresql_insert(JudgeCacheRow).values(**values)
            elif dialect == "sqlite":
                statement = sqlite_insert(JudgeCacheRow).values(**values)
            else:
                raise RuntimeError(f"unsupported database dialect: {dialect}")
            await session.execute(statement.on_conflict_do_nothing(index_elements=["cache_key"]))

    @staticmethod
    def _validate(key: str) -> None:
        if _KEY.fullmatch(key) is None:
            raise ValueError("judge cache key must be a 64-character lowercase hex digest")
