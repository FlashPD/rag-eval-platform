"""Index-version and document-embedding persistence."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ragops.contracts import (
    DocumentEmbedding,
    IndexBuildState,
    IndexVersion,
    IndexVersionSpec,
)
from ragops.persistence.models import DocumentEmbeddingRow, IndexVersionRow
from ragops.persistence.time import as_utc, optional_as_utc


class IndexVersionRepository(Protocol):
    async def create(self, spec: IndexVersionSpec) -> IndexVersion: ...

    async def get(self, index_version_id: UUID) -> IndexVersion | None: ...

    async def get_by_configuration(
        self, corpus_version_id: UUID, configuration_hash: str
    ) -> IndexVersion | None: ...

    async def refresh_progress(self, index_version_id: UUID) -> IndexVersion: ...

    async def advance_progress(
        self, index_version_id: UUID, *, inserted_count: int
    ) -> IndexVersion: ...


class EmbeddingRepository(Protocol):
    async def add_missing(self, embeddings: Sequence[DocumentEmbedding]) -> int: ...

    async def count(self, index_version_id: UUID) -> int: ...

    async def get_for_documents(
        self, index_version_id: UUID, document_ids: Sequence[UUID]
    ) -> dict[UUID, tuple[float, ...]]: ...

    async def missing_document_ids(
        self, index_version_id: UUID, document_ids: Sequence[UUID]
    ) -> set[UUID]: ...


def index_version_contract(row: IndexVersionRow) -> IndexVersion:
    if row.dimension != 384:
        raise ValueError(f"unsupported persisted embedding dimension: {row.dimension}")
    return IndexVersion(
        id=row.id,
        dataset_id=row.dataset_id,
        corpus_version_id=row.corpus_version_id,
        corpus_hash=row.corpus_hash,
        configuration_hash=row.configuration_hash,
        embedding_model=row.embedding_model,
        dimension=384,
        normalized=row.normalized,
        hnsw_parameters=row.hnsw_parameters,
        bm25_artifact_hash=row.bm25_artifact_hash,
        total_document_count=row.total_document_count,
        state=IndexBuildState(row.state),
        embedded_document_count=row.embedded_document_count,
        created_at=as_utc(row.created_at),
        completed_at=optional_as_utc(row.completed_at),
    )


class SqlAlchemyIndexVersionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, spec: IndexVersionSpec) -> IndexVersion:
        row = IndexVersionRow(**spec.model_dump())
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return index_version_contract(row)

    async def get(self, index_version_id: UUID) -> IndexVersion | None:
        row = await self._session.get(IndexVersionRow, index_version_id)
        return index_version_contract(row) if row is not None else None

    async def get_by_configuration(
        self, corpus_version_id: UUID, configuration_hash: str
    ) -> IndexVersion | None:
        row = await self._session.scalar(
            select(IndexVersionRow).where(
                IndexVersionRow.corpus_version_id == corpus_version_id,
                IndexVersionRow.configuration_hash == configuration_hash,
            )
        )
        return index_version_contract(row) if row is not None else None

    async def refresh_progress(self, index_version_id: UUID) -> IndexVersion:
        row = await self._session.get(IndexVersionRow, index_version_id)
        if row is None:
            raise KeyError(f"index version not found: {index_version_id}")
        embedded_count = int(
            await self._session.scalar(
                select(func.count())
                .select_from(DocumentEmbeddingRow)
                .where(DocumentEmbeddingRow.index_version_id == index_version_id)
            )
            or 0
        )
        if embedded_count > row.total_document_count:
            raise ValueError("embedded document count exceeds the index corpus size")
        if row.state == IndexBuildState.READY.value and embedded_count < row.total_document_count:
            raise ValueError("a ready index is missing persisted embeddings")
        row.embedded_document_count = embedded_count
        if embedded_count == row.total_document_count and row.state != IndexBuildState.READY.value:
            row.state = IndexBuildState.READY.value
            row.completed_at = datetime.now(UTC)
        await self._session.flush()
        await self._session.refresh(row)
        return index_version_contract(row)

    async def advance_progress(
        self, index_version_id: UUID, *, inserted_count: int
    ) -> IndexVersion:
        """Advance one committed batch without recounting the growing embedding table."""
        if inserted_count < 0:
            raise ValueError("inserted embedding count cannot be negative")
        row = await self._session.get(IndexVersionRow, index_version_id, with_for_update=True)
        if row is None:
            raise KeyError(f"index version not found: {index_version_id}")
        embedded_count = row.embedded_document_count + inserted_count
        if embedded_count > row.total_document_count:
            raise ValueError("embedded document count exceeds the index corpus size")
        row.embedded_document_count = embedded_count
        if embedded_count == row.total_document_count and row.state != IndexBuildState.READY.value:
            row.state = IndexBuildState.READY.value
            row.completed_at = datetime.now(UTC)
        await self._session.flush()
        await self._session.refresh(row)
        return index_version_contract(row)


class SqlAlchemyEmbeddingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_missing(self, embeddings: Sequence[DocumentEmbedding]) -> int:
        """Insert a resumable batch, ignoring documents already embedded for the index."""
        if not embeddings:
            return 0

        values = [
            {
                "document_id": embedding.document_id,
                "index_version_id": embedding.index_version_id,
                "embedding": list(embedding.values),
            }
            for embedding in embeddings
        ]
        bind = self._session.get_bind()
        statement: Any
        if bind.dialect.name == "postgresql":
            statement = postgresql_insert(DocumentEmbeddingRow).values(values)
            statement = statement.on_conflict_do_nothing(
                index_elements=["document_id", "index_version_id"]
            )
        elif bind.dialect.name == "sqlite":
            statement = sqlite_insert(DocumentEmbeddingRow).values(values)
            statement = statement.on_conflict_do_nothing(
                index_elements=["document_id", "index_version_id"]
            )
        else:
            raise RuntimeError(f"unsupported database dialect: {bind.dialect.name}")

        statement = statement.returning(DocumentEmbeddingRow.id)
        inserted_ids = (await self._session.execute(statement)).scalars().all()
        return len(inserted_ids)

    async def count(self, index_version_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(DocumentEmbeddingRow)
            .where(DocumentEmbeddingRow.index_version_id == index_version_id)
        )
        return int(await self._session.scalar(statement) or 0)

    async def get_for_documents(
        self, index_version_id: UUID, document_ids: Sequence[UUID]
    ) -> dict[UUID, tuple[float, ...]]:
        if not document_ids:
            return {}
        statement = select(DocumentEmbeddingRow.document_id, DocumentEmbeddingRow.embedding).where(
            DocumentEmbeddingRow.index_version_id == index_version_id,
            DocumentEmbeddingRow.document_id.in_(document_ids),
        )
        rows = (await self._session.execute(statement)).all()
        return {
            document_id: tuple(float(value) for value in embedding)
            for document_id, embedding in rows
        }

    async def missing_document_ids(
        self, index_version_id: UUID, document_ids: Sequence[UUID]
    ) -> set[UUID]:
        if not document_ids:
            return set()
        statement = select(DocumentEmbeddingRow.document_id).where(
            DocumentEmbeddingRow.index_version_id == index_version_id,
            DocumentEmbeddingRow.document_id.in_(document_ids),
        )
        present = set((await self._session.scalars(statement)).all())
        return set(document_ids) - present
