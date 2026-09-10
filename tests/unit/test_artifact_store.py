import asyncio
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from ragops.artifact_store import LocalArtifactStore, S3ArtifactStore, build_artifact_store
from ragops.config import Settings


class FakePaginator:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self._objects = objects

    def paginate(self, **kwargs: str) -> Iterable[Mapping[str, Any]]:
        prefix = kwargs["Prefix"]
        yield {
            "Contents": [{"Key": key} for key in sorted(self._objects) if key.startswith(prefix)]
        }


class FakeS3Client:
    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects = objects or {}
        self.downloads: list[tuple[str, str]] = []
        self.uploads: list[tuple[str, str]] = []

    def get_paginator(self, operation_name: str) -> FakePaginator:
        assert operation_name == "list_objects_v2"
        return FakePaginator(self.objects)

    def download_file(self, bucket: str, key: str, filename: str) -> None:
        self.downloads.append((bucket, key))
        Path(filename).write_bytes(self.objects[key])

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        self.uploads.append((bucket, key))
        self.objects[key] = Path(filename).read_bytes()


def test_runtime_hydration_downloads_only_bm25_objects_atomically(tmp_path: Path) -> None:
    client = FakeS3Client(
        {
            "production/artifacts/bm25/hash/index.npy": b"index",
            "production/artifacts/datasets/scifact.zip": b"archive",
            "production/evals/runs/id/report.json": b"{}",
        }
    )
    store = S3ArtifactStore(
        client=client,
        bucket="artifact-bucket",
        artifact_root=tmp_path,
        key_prefix="/production/",
    )

    count = asyncio.run(store.hydrate_runtime())

    assert count == 1
    assert (tmp_path / "bm25" / "hash" / "index.npy").read_bytes() == b"index"
    assert not (tmp_path / "datasets").exists()
    assert not list(tmp_path.rglob("*.part"))


def test_ingestion_hydration_downloads_dataset_cache_and_indexes(tmp_path: Path) -> None:
    client = FakeS3Client(
        {
            "artifacts/bm25/hash/index.npy": b"index",
            "artifacts/datasets/scifact.zip": b"archive",
        }
    )
    store = S3ArtifactStore(
        client=client,
        bucket="artifact-bucket",
        artifact_root=tmp_path,
    )

    count = asyncio.run(store.hydrate_ingestion())

    assert count == 2
    assert (tmp_path / "datasets" / "scifact.zip").read_bytes() == b"archive"
    assert (tmp_path / "bm25" / "hash" / "index.npy").read_bytes() == b"index"


def test_hydration_rejects_keys_that_escape_the_local_namespace(tmp_path: Path) -> None:
    client = FakeS3Client({"artifacts/bm25/../outside": b"unsafe"})
    store = S3ArtifactStore(
        client=client,
        bucket="artifact-bucket",
        artifact_root=tmp_path,
    )

    with pytest.raises(ValueError, match="unsafe S3 artifact key"):
        asyncio.run(store.hydrate_runtime())

    assert not (tmp_path / "outside").exists()


def test_ingestion_publication_uses_stable_artifact_keys(tmp_path: Path) -> None:
    content_hash = "a" * 64
    dataset = tmp_path / "datasets" / "scifact.zip"
    index = tmp_path / "bm25" / content_hash / "index.npy"
    dataset.parent.mkdir(parents=True)
    index.parent.mkdir(parents=True)
    dataset.write_bytes(b"archive")
    index.write_bytes(b"index")
    client = FakeS3Client()
    store = S3ArtifactStore(
        client=client,
        bucket="artifact-bucket",
        artifact_root=tmp_path,
        key_prefix="production",
    )

    count = asyncio.run(store.publish_ingestion(index.parent))

    assert count == 2
    assert client.objects == {
        "production/artifacts/datasets/scifact.zip": b"archive",
        f"production/artifacts/bm25/{content_hash}/index.npy": b"index",
    }


def test_report_publication_uses_the_run_id(tmp_path: Path) -> None:
    run_id = uuid4()
    report_directory = tmp_path / str(run_id)
    report_directory.mkdir()
    markdown = report_directory / "report.md"
    json = report_directory / "report.json"
    markdown.write_text("# Report", encoding="utf-8")
    json.write_text("{}", encoding="utf-8")
    client = FakeS3Client()
    store = S3ArtifactStore(
        client=client,
        bucket="artifact-bucket",
        artifact_root=tmp_path / "artifacts",
    )

    count = asyncio.run(store.publish_report(run_id, (markdown, json)))

    assert count == 2
    assert client.objects == {
        f"evals/runs/{run_id}/report.md": b"# Report",
        f"evals/runs/{run_id}/report.json": b"{}",
    }


def test_store_is_local_when_no_bucket_is_configured(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        database_url="sqlite+aiosqlite:///:memory:",
        artifact_directory=tmp_path,
    )

    store = build_artifact_store(settings)

    assert isinstance(store, LocalArtifactStore)
    assert asyncio.run(store.hydrate_runtime()) == 0
