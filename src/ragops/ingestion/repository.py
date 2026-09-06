"""Resumable relational writes for BEIR ingestion."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ragops.contracts import (
    LoadedDataset,
    PersistedCorpus,
    PersistedDocument,
    SourceDocument,
    SourceQrel,
    SourceQuery,
)
from ragops.persistence.models import (
    CorpusVersionRow,
    DatasetRow,
    DocumentRow,
    QrelRow,
    QueryRow,
)


async def _insert_missing(
    session: AsyncSession,
    model: type[Any],
    values: Sequence[dict[str, Any]],
    *,
    index_elements: Sequence[str],
) -> int:
    if not values:
        return 0
    dialect = session.get_bind().dialect.name
    statement: Any
    if dialect == "postgresql":
        statement = postgresql_insert(model).values(list(values))
    elif dialect == "sqlite":
        statement = sqlite_insert(model).values(list(values))
    else:
        raise RuntimeError(f"unsupported database dialect: {dialect}")
    statement = statement.on_conflict_do_nothing(index_elements=index_elements).returning(model.id)
    return len((await session.execute(statement)).scalars().all())


class IngestionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create_dataset(
        self,
        *,
        name: str,
        version: str,
        split: str,
        license_name: str,
    ) -> DatasetRow:
        row = await self._session.scalar(
            select(DatasetRow).where(
                DatasetRow.name == name,
                DatasetRow.version == version,
                DatasetRow.split == split,
            )
        )
        if row is not None:
            if row.license_name != license_name:
                raise ValueError("an existing dataset version cannot change its recorded license")
            return row
        row = DatasetRow(
            name=name,
            version=version,
            split=split,
            license_name=license_name,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get_or_create_corpus(
        self, *, dataset_id: UUID, content_hash: str, document_count: int
    ) -> CorpusVersionRow:
        row = await self._session.scalar(
            select(CorpusVersionRow).where(
                CorpusVersionRow.dataset_id == dataset_id,
                CorpusVersionRow.content_hash == content_hash,
            )
        )
        if row is not None:
            if row.document_count != document_count:
                raise ValueError("corpus hash is associated with a different document count")
            return row
        row = CorpusVersionRow(
            dataset_id=dataset_id,
            content_hash=content_hash,
            document_count=document_count,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def add_documents(
        self, corpus_version_id: UUID, documents: Sequence[SourceDocument]
    ) -> int:
        values = [
            {
                "corpus_version_id": corpus_version_id,
                "external_id": document.external_id,
                "title": document.title,
                "text": document.text,
            }
            for document in documents
        ]
        return await _insert_missing(
            self._session,
            DocumentRow,
            values,
            index_elements=["corpus_version_id", "external_id"],
        )

    async def add_queries(self, dataset_id: UUID, queries: Sequence[SourceQuery]) -> int:
        values = [
            {
                "dataset_id": dataset_id,
                "external_id": query.external_id,
                "text": query.text,
            }
            for query in queries
        ]
        return await _insert_missing(
            self._session,
            QueryRow,
            values,
            index_elements=["dataset_id", "external_id"],
        )

    async def add_qrels(
        self,
        *,
        dataset_id: UUID,
        corpus_version_id: UUID,
        qrels: Sequence[SourceQrel],
    ) -> int:
        query_rows = await self._session.execute(
            select(QueryRow.external_id, QueryRow.id).where(QueryRow.dataset_id == dataset_id)
        )
        document_rows = await self._session.execute(
            select(DocumentRow.external_id, DocumentRow.id).where(
                DocumentRow.corpus_version_id == corpus_version_id
            )
        )
        query_ids: dict[str, UUID] = {
            external_id: row_id for external_id, row_id in query_rows.tuples()
        }
        document_ids: dict[str, UUID] = {
            external_id: row_id for external_id, row_id in document_rows.tuples()
        }
        values = [
            {
                "query_id": query_ids[qrel.query_external_id],
                "document_id": document_ids[qrel.document_external_id],
                "relevance": qrel.relevance,
            }
            for qrel in qrels
        ]
        return await _insert_missing(
            self._session,
            QrelRow,
            values,
            index_elements=["query_id", "document_id"],
        )

    async def load_corpus(self, *, dataset_id: UUID, corpus_version_id: UUID) -> PersistedCorpus:
        document_rows = (
            await self._session.scalars(
                select(DocumentRow)
                .where(DocumentRow.corpus_version_id == corpus_version_id)
                .order_by(DocumentRow.external_id)
            )
        ).all()
        query_count = int(
            await self._session.scalar(
                select(func.count()).select_from(QueryRow).where(QueryRow.dataset_id == dataset_id)
            )
            or 0
        )
        qrel_count = int(
            await self._session.scalar(
                select(func.count())
                .select_from(QrelRow)
                .join(QueryRow, QrelRow.query_id == QueryRow.id)
                .where(QueryRow.dataset_id == dataset_id)
            )
            or 0
        )
        return PersistedCorpus(
            dataset_id=dataset_id,
            corpus_version_id=corpus_version_id,
            documents=tuple(
                PersistedDocument(
                    id=row.id,
                    external_id=row.external_id,
                    title=row.title,
                    text=row.text,
                )
                for row in document_rows
            ),
            query_count=query_count,
            qrel_count=qrel_count,
        )


def validate_persisted_counts(dataset: LoadedDataset, corpus: PersistedCorpus) -> None:
    observed = (len(corpus.documents), corpus.query_count, corpus.qrel_count)
    expected = (len(dataset.documents), len(dataset.queries), len(dataset.qrels))
    if observed != expected:
        raise ValueError(f"persisted dataset counts do not match source: {observed=} {expected=}")
