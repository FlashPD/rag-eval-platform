"""Dataset ingestion contracts."""

from pathlib import Path
from uuid import UUID

from pydantic import Field, model_validator

from ragops.contracts.base import Contract
from ragops.contracts.resources import IndexVersion


class SourceDocument(Contract):
    external_id: str = Field(min_length=1, max_length=255)
    title: str = ""
    text: str = Field(min_length=1)


class SourceQuery(Contract):
    external_id: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1)


class SourceQrel(Contract):
    query_external_id: str = Field(min_length=1, max_length=255)
    document_external_id: str = Field(min_length=1, max_length=255)
    relevance: int = Field(ge=0)


class LoadedDataset(Contract):
    documents: tuple[SourceDocument, ...] = Field(min_length=1)
    queries: tuple[SourceQuery, ...] = Field(min_length=1)
    qrels: tuple[SourceQrel, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> "LoadedDataset":
        document_ids = [document.external_id for document in self.documents]
        query_ids = [query.external_id for query in self.queries]
        document_id_set = set(document_ids)
        query_id_set = set(query_ids)
        if len(set(document_ids)) != len(document_ids):
            raise ValueError("dataset contains duplicate document identifiers")
        if len(set(query_ids)) != len(query_ids):
            raise ValueError("dataset contains duplicate query identifiers")
        qrel_keys = [(qrel.query_external_id, qrel.document_external_id) for qrel in self.qrels]
        if len(set(qrel_keys)) != len(qrel_keys):
            raise ValueError("dataset contains duplicate qrels")
        missing_documents = {
            qrel.document_external_id
            for qrel in self.qrels
            if qrel.document_external_id not in document_id_set
        }
        missing_queries = {
            qrel.query_external_id
            for qrel in self.qrels
            if qrel.query_external_id not in query_id_set
        }
        if missing_documents or missing_queries:
            raise ValueError(
                "qrels reference unknown identifiers: "
                f"documents={sorted(missing_documents)}, queries={sorted(missing_queries)}"
            )
        return self


class PersistedDocument(Contract):
    id: UUID
    external_id: str
    title: str
    text: str


class PersistedCorpus(Contract):
    dataset_id: UUID
    corpus_version_id: UUID
    documents: tuple[PersistedDocument, ...]
    query_count: int = Field(ge=0)
    qrel_count: int = Field(ge=0)


class ArtifactReference(Contract):
    content_hash: str = Field(min_length=64, max_length=64)
    path: Path


class IngestionResult(Contract):
    dataset: str
    split: str
    corpus_hash: str = Field(min_length=64, max_length=64)
    bm25_artifact: ArtifactReference
    index_version: IndexVersion
    inserted_documents: int = Field(ge=0)
    inserted_queries: int = Field(ge=0)
    inserted_qrels: int = Field(ge=0)
    inserted_embeddings: int = Field(ge=0)
