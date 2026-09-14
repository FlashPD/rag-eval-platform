from uuid import uuid4

from sqlalchemy.dialects import postgresql

from ragops.retrieval.store import dense_search_statement


def test_dense_query_uses_pgvector_cosine_distance() -> None:
    statement = dense_search_statement(uuid4(), [0.0] * 383 + [1.0], k=10)

    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "<=>" in sql
    assert "document_embeddings.index_version_id" in sql
    assert "LIMIT" in sql
