"""Repository protocols and SQLAlchemy implementations."""

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ragops.contracts import Dataset, EvalProgress, EvalRun, EvalRunSpec, EvalRunState
from ragops.contracts.evaluation import ensure_state_transition
from ragops.persistence.models import DatasetRow, EvalRunRow, EvalRunVariantRow
from ragops.persistence.time import as_utc, optional_as_utc


class DatasetRepository(Protocol):
    async def create(
        self, *, name: str, version: str, split: str, license_name: str
    ) -> Dataset: ...

    async def get_by_key(self, *, name: str, version: str, split: str) -> Dataset | None: ...


class EvaluationRunRepository(Protocol):
    async def create(
        self,
        spec: EvalRunSpec,
        *,
        variant_hashes: dict[str, str],
        git_commit: str | None = None,
        image_digest: str | None = None,
    ) -> EvalRun: ...

    async def get(self, run_id: UUID) -> EvalRun | None: ...

    async def get_variant_hashes(self, run_id: UUID) -> dict[str, str]: ...

    async def set_state(self, run_id: UUID, state: EvalRunState) -> EvalRun: ...

    async def set_progress(
        self, run_id: UUID, *, completed_queries: int, total_queries: int
    ) -> EvalRun: ...


def _dataset_contract(row: DatasetRow) -> Dataset:
    return Dataset(
        id=row.id,
        name=row.name,
        version=row.version,
        split=row.split,
        license_name=row.license_name,
        created_at=as_utc(row.created_at),
    )


def _eval_run_contract(row: EvalRunRow) -> EvalRun:
    return EvalRun(
        id=row.id,
        spec=EvalRunSpec.model_validate(row.spec),
        state=EvalRunState(row.state),
        progress=EvalProgress(
            completed_queries=row.completed_queries,
            total_queries=row.total_queries,
        ),
        git_commit=row.git_commit,
        image_digest=row.image_digest,
        created_at=as_utc(row.created_at),
        completed_at=optional_as_utc(row.completed_at),
    )


class SqlAlchemyDatasetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, name: str, version: str, split: str, license_name: str) -> Dataset:
        row = DatasetRow(name=name, version=version, split=split, license_name=license_name)
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return _dataset_contract(row)

    async def get_by_key(self, *, name: str, version: str, split: str) -> Dataset | None:
        statement = select(DatasetRow).where(
            DatasetRow.name == name,
            DatasetRow.version == version,
            DatasetRow.split == split,
        )
        row = await self._session.scalar(statement)
        return _dataset_contract(row) if row is not None else None


class SqlAlchemyEvaluationRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        spec: EvalRunSpec,
        *,
        variant_hashes: dict[str, str],
        git_commit: str | None = None,
        image_digest: str | None = None,
    ) -> EvalRun:
        missing_hashes = set(spec.variants) - variant_hashes.keys()
        if missing_hashes:
            missing = ", ".join(sorted(missing_hashes))
            raise ValueError(f"missing configuration hashes for variants: {missing}")

        row = EvalRunRow(
            spec=spec.model_dump(mode="json"),
            state=EvalRunState.CREATED.value,
            git_commit=git_commit,
            image_digest=image_digest,
        )
        self._session.add(row)
        await self._session.flush()
        self._session.add_all(
            EvalRunVariantRow(
                eval_run_id=row.id,
                name=name,
                configuration_hash=variant_hashes[name],
            )
            for name in spec.variants
        )
        await self._session.flush()
        await self._session.refresh(row)
        return _eval_run_contract(row)

    async def get(self, run_id: UUID) -> EvalRun | None:
        row = await self._session.get(EvalRunRow, run_id)
        return _eval_run_contract(row) if row is not None else None

    async def get_variant_hashes(self, run_id: UUID) -> dict[str, str]:
        rows = await self._session.execute(
            select(EvalRunVariantRow.name, EvalRunVariantRow.configuration_hash).where(
                EvalRunVariantRow.eval_run_id == run_id
            )
        )
        return dict(rows.tuples().all())

    async def set_state(self, run_id: UUID, state: EvalRunState) -> EvalRun:
        row = await self._session.get(EvalRunRow, run_id)
        if row is None:
            raise KeyError(f"evaluation run not found: {run_id}")

        current = EvalRunState(row.state)
        ensure_state_transition(current, state)
        row.state = state.value
        if state in {EvalRunState.COMPLETED, EvalRunState.FAILED, EvalRunState.CANCELLED}:
            row.completed_at = datetime.now(UTC)
        await self._session.flush()
        await self._session.refresh(row)
        return _eval_run_contract(row)

    async def set_progress(
        self, run_id: UUID, *, completed_queries: int, total_queries: int
    ) -> EvalRun:
        if completed_queries < 0 or total_queries < 0 or completed_queries > total_queries:
            raise ValueError("evaluation progress must satisfy 0 <= completed <= total")
        row = await self._session.get(EvalRunRow, run_id)
        if row is None:
            raise KeyError(f"evaluation run not found: {run_id}")
        if completed_queries < row.completed_queries:
            raise ValueError("evaluation progress cannot decrease")
        if row.total_queries not in {0, total_queries}:
            raise ValueError("evaluation total cannot change after it is initialized")
        row.completed_queries = completed_queries
        row.total_queries = total_queries
        await self._session.flush()
        await self._session.refresh(row)
        return _eval_run_contract(row)
