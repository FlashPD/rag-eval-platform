"""Persistence operations used by retrieval evaluation execution."""

from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ragops.contracts import AnswerResponse, EvaluationQuery, JudgeVerdict, QueryResult
from ragops.persistence.models import (
    DatasetRow,
    DocumentRow,
    EvalQueryResultRow,
    EvalRunRow,
    QrelRow,
    QueryRow,
)


class EvaluationDataRepository(Protocol):
    async def load_queries(
        self, *, dataset_name: str, dataset_version: str, split: str
    ) -> tuple[EvaluationQuery, ...]: ...

    async def completed_work(self, run_id: UUID) -> set[tuple[UUID, str]]: ...

    async def load_results(self, run_id: UUID) -> tuple[QueryResult, ...]: ...

    async def add_result(self, result: QueryResult, *, query_id: UUID) -> bool: ...

    async def update_answer(
        self,
        *,
        run_id: UUID,
        query_id: UUID,
        variant: str,
        answer: AnswerResponse,
        deterministic_scores: dict[str, float],
        scifact_gold_label: str | None,
    ) -> None: ...

    async def update_judges(
        self,
        *,
        run_id: UUID,
        query_id: UUID,
        variant: str,
        verdicts: dict[str, JudgeVerdict],
    ) -> None: ...


class SqlAlchemyEvaluationDataRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load_queries(
        self, *, dataset_name: str, dataset_version: str, split: str
    ) -> tuple[EvaluationQuery, ...]:
        dataset = await self._session.scalar(
            select(DatasetRow).where(
                DatasetRow.name == dataset_name,
                DatasetRow.version == dataset_version,
                DatasetRow.split == split,
            )
        )
        if dataset is None:
            raise ValueError(f"dataset is not ingested: {dataset_name}/{dataset_version}/{split}")
        queries = (
            await self._session.scalars(
                select(QueryRow)
                .where(QueryRow.dataset_id == dataset.id)
                .order_by(QueryRow.external_id)
            )
        ).all()
        qrel_rows = (
            await self._session.execute(
                select(QrelRow.query_id, DocumentRow.external_id, QrelRow.relevance)
                .join(DocumentRow, DocumentRow.id == QrelRow.document_id)
                .join(QueryRow, QueryRow.id == QrelRow.query_id)
                .where(QueryRow.dataset_id == dataset.id)
            )
        ).tuples()
        qrels_by_query: dict[UUID, dict[str, int]] = {}
        for query_id, document_id, relevance in qrel_rows:
            qrels_by_query.setdefault(query_id, {})[document_id] = relevance
        return tuple(
            EvaluationQuery(
                id=query.id,
                external_id=query.external_id,
                text=query.text,
                qrels=qrels_by_query.get(query.id, {}),
                metadata=query.query_metadata,
            )
            for query in queries
        )

    async def completed_work(self, run_id: UUID) -> set[tuple[UUID, str]]:
        rows = await self._session.execute(
            select(EvalQueryResultRow.query_id, EvalQueryResultRow.variant).where(
                EvalQueryResultRow.eval_run_id == run_id
            )
        )
        return set(rows.tuples().all())

    async def load_results(self, run_id: UUID) -> tuple[QueryResult, ...]:
        rows = (
            await self._session.execute(
                select(EvalQueryResultRow, QueryRow.external_id)
                .join(QueryRow, QueryRow.id == EvalQueryResultRow.query_id)
                .where(EvalQueryResultRow.eval_run_id == run_id)
                .order_by(EvalQueryResultRow.variant, QueryRow.external_id)
            )
        ).tuples()
        return tuple(
            QueryResult.model_validate(
                {
                    "run_id": row.eval_run_id,
                    "variant": row.variant,
                    "query_id": query_external_id,
                    "ranked_document_ids": row.ranked_document_ids,
                    "stage_timings": row.stage_timings,
                    "answer": row.generation_record,
                    "deterministic_scores": row.deterministic_scores,
                    "judge_scores": row.judge_scores,
                    "judge_records": row.judge_records,
                    "scifact_gold_label": row.scifact_gold_label,
                    "token_cost_usd": row.token_cost_usd,
                }
            )
            for row, query_external_id in rows
        )

    async def add_result(self, result: QueryResult, *, query_id: UUID) -> bool:
        values = {
            "eval_run_id": result.run_id,
            "query_id": query_id,
            "variant": result.variant,
            "ranked_document_ids": list(result.ranked_document_ids),
            "stage_timings": [timing.model_dump(mode="json") for timing in result.stage_timings],
            "generation_record": (
                result.answer.model_dump(mode="json") if result.answer is not None else None
            ),
            "deterministic_scores": result.deterministic_scores,
            "judge_scores": result.judge_scores,
            "judge_records": {
                profile: verdict.model_dump(mode="json")
                for profile, verdict in result.judge_records.items()
            },
            "scifact_gold_label": result.scifact_gold_label,
            "token_cost_usd": result.token_cost_usd,
        }
        dialect = self._session.get_bind().dialect.name
        statement: Any
        if dialect == "postgresql":
            statement = postgresql_insert(EvalQueryResultRow).values(values)
        elif dialect == "sqlite":
            statement = sqlite_insert(EvalQueryResultRow).values(values)
        else:
            raise RuntimeError(f"unsupported database dialect: {dialect}")
        statement = statement.on_conflict_do_nothing(
            index_elements=["eval_run_id", "variant", "query_id"]
        ).returning(EvalQueryResultRow.id)
        inserted = (await self._session.scalar(statement)) is not None
        if inserted:
            completed = int(
                await self._session.scalar(
                    select(func.count())
                    .select_from(EvalQueryResultRow)
                    .where(EvalQueryResultRow.eval_run_id == result.run_id)
                )
                or 0
            )
            run = await self._session.get(EvalRunRow, result.run_id)
            if run is None:
                raise KeyError(f"evaluation run not found: {result.run_id}")
            if completed > run.total_queries:
                raise ValueError("persisted evaluation results exceed the configured total")
            run.completed_queries = completed
            await self._session.flush()
        return inserted

    async def update_answer(
        self,
        *,
        run_id: UUID,
        query_id: UUID,
        variant: str,
        answer: AnswerResponse,
        deterministic_scores: dict[str, float],
        scifact_gold_label: str | None,
    ) -> None:
        row = await self._session.scalar(
            select(EvalQueryResultRow).where(
                EvalQueryResultRow.eval_run_id == run_id,
                EvalQueryResultRow.query_id == query_id,
                EvalQueryResultRow.variant == variant,
            )
        )
        if row is None:
            raise KeyError(f"evaluation result not found for {query_id}/{variant}")
        if row.generation_record is None:
            row.generation_record = answer.model_dump(mode="json")
            row.deterministic_scores = {**row.deterministic_scores, **deterministic_scores}
            row.scifact_gold_label = scifact_gold_label
            row.token_cost_usd = Decimal(str(row.token_cost_usd)) + answer.usage.cost_usd
            await self._session.flush()

    async def update_judges(
        self,
        *,
        run_id: UUID,
        query_id: UUID,
        variant: str,
        verdicts: dict[str, JudgeVerdict],
    ) -> None:
        row = await self._session.scalar(
            select(EvalQueryResultRow).where(
                EvalQueryResultRow.eval_run_id == run_id,
                EvalQueryResultRow.query_id == query_id,
                EvalQueryResultRow.variant == variant,
            )
        )
        if row is None:
            raise KeyError(f"evaluation result not found for {query_id}/{variant}")
        records = dict(row.judge_records)
        scores = dict(row.judge_scores)
        new_cost = Decimal("0")
        for profile, verdict in verdicts.items():
            if profile in records:
                continue
            records[profile] = verdict.model_dump(mode="json")
            scores[f"{profile}.faithfulness"] = verdict.faithfulness
            scores[f"{profile}.relevance"] = verdict.relevance
            new_cost += verdict.usage.cost_usd
        row.judge_records = records
        row.judge_scores = scores
        row.token_cost_usd = Decimal(str(row.token_cost_usd)) + new_cost
        await self._session.flush()
