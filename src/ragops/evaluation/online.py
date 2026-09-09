"""Deterministic online sampling and asynchronous judge persistence."""

import hashlib
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from pydantic import JsonValue
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ragops.contracts import ONLINE_JUDGE_JOB_KIND, AnswerResponse, JobSpec, JudgeVerdict
from ragops.evaluation.judging import VersionedJudgePromptRenderer
from ragops.persistence.job_queue import SqlAlchemyJobQueue
from ragops.persistence.models import OnlineEvaluationRow
from ragops.protocols import Judge
from ragops.telemetry import record_judge_verdict


def selected_for_online_evaluation(trace_id: str, sample_rate: float) -> bool:
    if not 0 <= sample_rate <= 1:
        raise ValueError("online evaluation sample rate must be between zero and one")
    bucket = int.from_bytes(hashlib.sha256(trace_id.encode()).digest()[:8], "big")
    return bucket / (2**64) < sample_rate


class OnlineEvaluationSampler:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        sample_rate: float,
    ) -> None:
        if not 0 <= sample_rate <= 1:
            raise ValueError("online evaluation sample rate must be between zero and one")
        self._sessions = sessions
        self._sample_rate = sample_rate

    async def submit(self, *, query: str, answer: AnswerResponse) -> bool:
        if not selected_for_online_evaluation(answer.trace_id, self._sample_rate):
            return False
        async with self._sessions.begin() as session:
            await SqlAlchemyJobQueue(session).enqueue(
                JobSpec(
                    kind=ONLINE_JUDGE_JOB_KIND,
                    payload={"query": query, "answer": answer.model_dump(mode="json")},
                    idempotency_key=f"{ONLINE_JUDGE_JOB_KIND}:{answer.trace_id}",
                )
            )
        return True


def build_online_judge_handler(
    sessions: async_sessionmaker[AsyncSession],
    *,
    renderer: VersionedJudgePromptRenderer,
    judges: Mapping[str, Judge],
) -> Callable[[dict[str, JsonValue]], Awaitable[None]]:
    async def handle(payload: dict[str, JsonValue]) -> None:
        query = payload.get("query")
        raw_answer = payload.get("answer")
        if not isinstance(query, str) or not isinstance(raw_answer, dict):
            raise ValueError("online judge payload requires query and answer")
        answer = AnswerResponse.model_validate(raw_answer)
        request = renderer.render_for_query(query, answer)
        verdicts: list[JudgeVerdict] = []
        for profile, judge in judges.items():
            verdict = await judge.judge(request)
            verdicts.append(verdict)
            record_judge_verdict(profile=profile, verdict=verdict, source="online")
        values = {
            "trace_id": answer.trace_id,
            "answer_record": answer.model_dump(mode="json"),
            "judge_records": [verdict.model_dump(mode="json") for verdict in verdicts],
        }
        async with sessions.begin() as session:
            dialect = session.get_bind().dialect.name
            if dialect == "postgresql":
                statement: Any = postgresql_insert(OnlineEvaluationRow).values(**values)
            elif dialect == "sqlite":
                statement = sqlite_insert(OnlineEvaluationRow).values(**values)
            else:
                raise RuntimeError(f"unsupported database dialect: {dialect}")
            await session.execute(statement.on_conflict_do_nothing(index_elements=["trace_id"]))

    return handle
