import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config


@pytest.mark.integration
def test_initial_migration_upgrades_to_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "migration.db"
    monkeypatch.setenv("RAGOPS_DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")

    command.upgrade(Config("alembic.ini"), "head")

    with sqlite3.connect(database_path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert {
        "alembic_version",
        "datasets",
        "document_embeddings",
        "documents",
        "eval_query_results",
        "eval_runs",
        "generation_cache",
        "index_versions",
        "judge_cache",
        "jobs",
        "online_evaluations",
        "qrels",
        "queries",
    } <= tables

    command.downgrade(Config("alembic.ini"), "base")
    with sqlite3.connect(database_path) as connection:
        remaining_tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    assert remaining_tables == {"alembic_version"}
