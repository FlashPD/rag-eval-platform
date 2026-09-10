"""S3-backed hydration and publication for durable runtime artifacts."""

import asyncio
import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, cast
from uuid import UUID

import boto3  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from ragops.config import Settings


class S3Paginator(Protocol):
    def paginate(self, **kwargs: str) -> Iterable[Mapping[str, Any]]: ...


class S3Client(Protocol):
    def get_paginator(self, operation_name: str) -> S3Paginator: ...

    def download_file(self, bucket: str, key: str, filename: str) -> None: ...

    def upload_file(self, filename: str, bucket: str, key: str) -> None: ...


class ArtifactStore(Protocol):
    async def hydrate_runtime(self) -> int: ...

    async def hydrate_ingestion(self) -> int: ...

    async def publish_ingestion(self, bm25_artifact: Path) -> int: ...

    async def publish_report(self, run_id: UUID, files: Sequence[Path]) -> int: ...


class LocalArtifactStore:
    """No-op store used when no remote artifact bucket is configured."""

    async def hydrate_runtime(self) -> int:
        return 0

    async def hydrate_ingestion(self) -> int:
        return 0

    async def publish_ingestion(self, bm25_artifact: Path) -> int:
        return 0

    async def publish_report(self, run_id: UUID, files: Sequence[Path]) -> int:
        return 0


class S3ArtifactStore:
    """Mirror selected artifact namespaces between ephemeral storage and S3."""

    def __init__(
        self,
        *,
        client: S3Client,
        bucket: str,
        artifact_root: Path,
        key_prefix: str = "",
    ) -> None:
        self._client = client
        self._bucket = bucket
        self._artifact_root = artifact_root
        self._key_prefix = key_prefix.strip("/")

    async def hydrate_runtime(self) -> int:
        """Hydrate BM25 indexes required by API and worker processes."""
        return await asyncio.to_thread(self._hydrate_namespace, "artifacts/bm25")

    async def hydrate_ingestion(self) -> int:
        """Hydrate resumable dataset caches and any existing BM25 indexes."""
        counts = await asyncio.gather(
            asyncio.to_thread(self._hydrate_namespace, "artifacts/datasets"),
            asyncio.to_thread(self._hydrate_namespace, "artifacts/bm25"),
        )
        return sum(counts)

    async def publish_ingestion(self, bm25_artifact: Path) -> int:
        """Publish the dataset cache and the content-addressed BM25 index."""
        bm25_root = self._artifact_root / "bm25"
        artifact = bm25_artifact.resolve()
        is_content_hash = len(artifact.name) == 64 and all(
            character in "0123456789abcdef" for character in artifact.name
        )
        if artifact.parent != bm25_root.resolve() or not artifact.is_dir() or not is_content_hash:
            raise ValueError("BM25 artifact must be a direct child of the configured BM25 root")

        counts = await asyncio.gather(
            asyncio.to_thread(
                self._publish_tree,
                self._artifact_root / "datasets",
                "artifacts/datasets",
            ),
            asyncio.to_thread(
                self._publish_tree,
                artifact,
                f"artifacts/bm25/{artifact.name}",
            ),
        )
        return sum(counts)

    async def publish_report(self, run_id: UUID, files: Sequence[Path]) -> int:
        """Publish the canonical JSON and Markdown files for an evaluation run."""
        expected = {"report.json", "report.md"}
        names = {path.name for path in files}
        if names != expected or len(files) != len(expected):
            raise ValueError("evaluation publication requires report.json and report.md")
        if any(not path.is_file() for path in files):
            raise ValueError("evaluation report files must exist before publication")

        return await asyncio.to_thread(
            self._publish_files,
            tuple(files),
            f"evals/runs/{run_id}",
        )

    def _remote_prefix(self, namespace: str) -> str:
        return f"{self._key_prefix}/{namespace}" if self._key_prefix else namespace

    def _hydrate_namespace(self, namespace: str) -> int:
        remote_prefix = f"{self._remote_prefix(namespace).rstrip('/')}/"
        local_root = self._artifact_root / namespace.removeprefix("artifacts/")
        paginator = self._client.get_paginator("list_objects_v2")
        downloaded = 0
        for page in paginator.paginate(Bucket=self._bucket, Prefix=remote_prefix):
            contents = page.get("Contents", ())
            if not isinstance(contents, Iterable):
                raise TypeError("S3 listing Contents must be iterable")
            for item in contents:
                if not isinstance(item, Mapping):
                    raise TypeError("S3 listing entry is missing a string Key")
                key = item.get("Key")
                if not isinstance(key, str):
                    raise TypeError("S3 listing entry is missing a string Key")
                relative = self._safe_relative_key(key, remote_prefix)
                if relative is None:
                    continue
                destination = local_root.joinpath(*relative.split("/"))
                destination.parent.mkdir(parents=True, exist_ok=True)
                temporary = destination.with_name(f".{destination.name}.part")
                try:
                    self._client.download_file(self._bucket, key, str(temporary))
                    os.replace(temporary, destination)
                finally:
                    temporary.unlink(missing_ok=True)
                downloaded += 1
        return downloaded

    @staticmethod
    def _safe_relative_key(key: str, remote_prefix: str) -> str | None:
        if not key.startswith(remote_prefix):
            raise ValueError(f"S3 key is outside the requested prefix: {key}")
        relative = key.removeprefix(remote_prefix)
        if not relative:
            return None
        parts = relative.split("/")
        if any(part in {"", ".", ".."} or "\\" in part for part in parts):
            raise ValueError(f"unsafe S3 artifact key: {key}")
        return relative

    def _publish_tree(self, root: Path, namespace: str) -> int:
        if not root.exists():
            return 0
        root_resolved = root.resolve()
        files: list[Path] = []
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise ValueError(f"artifact trees cannot contain symbolic links: {path}")
            if path.is_file():
                resolved = path.resolve()
                if not resolved.is_relative_to(root_resolved):
                    raise ValueError(f"artifact file escapes its configured root: {path}")
                files.append(path)
        return self._publish_files(files, namespace, relative_to=root)

    def _publish_files(
        self,
        files: Sequence[Path],
        namespace: str,
        *,
        relative_to: Path | None = None,
    ) -> int:
        remote_prefix = self._remote_prefix(namespace).rstrip("/")
        for path in files:
            relative = path.relative_to(relative_to).as_posix() if relative_to else path.name
            self._client.upload_file(str(path), self._bucket, f"{remote_prefix}/{relative}")
        return len(files)


def build_artifact_store(settings: "Settings", *, client: S3Client | None = None) -> ArtifactStore:
    """Build the configured artifact store without requiring AWS for local runs."""
    if settings.artifact_bucket is None:
        return LocalArtifactStore()
    if client is None:
        client = cast(S3Client, boto3.client("s3"))
    return S3ArtifactStore(
        client=client,
        bucket=settings.artifact_bucket,
        artifact_root=settings.artifact_directory,
        key_prefix=settings.artifact_s3_prefix,
    )
