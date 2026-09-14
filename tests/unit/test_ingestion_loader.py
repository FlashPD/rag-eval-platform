import hashlib
import zipfile
from pathlib import Path

import pytest

from ragops.contracts import SourceDocument
from ragops.ingestion.hashing import hash_dataset
from ragops.ingestion.loader import load_beir_dataset
from ragops.ingestion.sources import (
    ChecksumMismatchError,
    _extract_zip_safely,
    verify_checksum,
)

FIXTURE_DIRECTORY = Path(__file__).parents[2] / "fixtures" / "tiny-beir"


def test_loads_beir_fixture_and_filters_queries_to_split() -> None:
    dataset = load_beir_dataset(FIXTURE_DIRECTORY, split="test")

    assert [document.external_id for document in dataset.documents] == [
        "doc-a",
        "doc-b",
        "doc-c",
    ]
    assert [query.external_id for query in dataset.queries] == ["q-1", "q-2"]
    assert len(dataset.qrels) == 2
    assert len(hash_dataset(dataset)) == 64


def test_source_document_preserves_an_empty_beir_corpus_row() -> None:
    document = SourceDocument(external_id="117276", title="", text="")

    assert document.title == ""
    assert document.text == ""


def test_checksum_verification_rejects_modified_file(tmp_path: Path) -> None:
    archive = tmp_path / "dataset.zip"
    archive.write_bytes(b"dataset")
    checksum = hashlib.md5(b"dataset", usedforsecurity=False).hexdigest()

    verify_checksum(archive, algorithm="md5", expected=checksum)
    with pytest.raises(ChecksumMismatchError, match="checksum mismatch"):
        verify_checksum(archive, algorithm="md5", expected="0" * 32)


def test_archive_extraction_rejects_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "malicious.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../escape.txt", "malicious")

    with pytest.raises(ValueError, match="escapes destination"):
        _extract_zip_safely(archive, tmp_path / "destination")
