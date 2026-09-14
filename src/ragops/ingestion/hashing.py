"""Stable hashing for source data and content-addressed artifacts."""

import hashlib
import json
from pathlib import Path
from typing import Any

from ragops.contracts import LoadedDataset


def hash_file(path: Path, algorithm: str = "sha256") -> str:
    hasher = hashlib.new(algorithm, usedforsecurity=False)
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            hasher.update(chunk)
    return hasher.hexdigest()


def hash_directory(path: Path) -> str:
    hasher = hashlib.sha256()
    for item in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        hasher.update(item.relative_to(path).as_posix().encode())
        hasher.update(b"\0")
        with item.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                hasher.update(chunk)
    return hasher.hexdigest()


def hash_json(value: Any) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def hash_dataset(dataset: LoadedDataset) -> str:
    return hash_json(
        {
            "documents": sorted(
                (document.model_dump(mode="json") for document in dataset.documents),
                key=lambda value: value["external_id"],
            ),
            "queries": sorted(
                (query.model_dump(mode="json") for query in dataset.queries),
                key=lambda value: value["external_id"],
            ),
            "qrels": sorted(
                (qrel.model_dump(mode="json") for qrel in dataset.qrels),
                key=lambda value: (
                    value["query_external_id"],
                    value["document_external_id"],
                ),
            ),
        }
    )
