"""Strict loader for the BEIR JSONL and TSV interchange format."""

import csv
import json
from pathlib import Path
from typing import Any

from ragops.contracts import LoadedDataset, SourceDocument, SourceQrel, SourceQuery


def _read_json_lines(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ValueError(f"required dataset file not found: {path}")
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"invalid JSON at {path}:{line_number}") from error
            if not isinstance(value, dict):
                raise ValueError(f"expected a JSON object at {path}:{line_number}")
            records.append(value)
    return records


def load_beir_dataset(directory: Path, *, split: str) -> LoadedDataset:
    """Load a BEIR corpus and retain only queries represented in the selected qrels."""
    qrels_path = directory / "qrels" / f"{split}.tsv"
    if not qrels_path.is_file():
        raise ValueError(f"qrels split not found: {qrels_path}")

    qrels: list[SourceQrel] = []
    with qrels_path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source, delimiter="\t")
        required = {"query-id", "corpus-id", "score"}
        if reader.fieldnames is None or not required <= set(reader.fieldnames):
            raise ValueError(f"invalid BEIR qrels header: {qrels_path}")
        for row in reader:
            qrels.append(
                SourceQrel(
                    query_external_id=row["query-id"],
                    document_external_id=row["corpus-id"],
                    relevance=int(row["score"]),
                )
            )

    selected_query_ids = {qrel.query_external_id for qrel in qrels}
    documents = tuple(
        SourceDocument(
            external_id=str(record["_id"]),
            title=str(record.get("title", "")),
            text=str(record["text"]),
        )
        for record in _read_json_lines(directory / "corpus.jsonl")
    )
    queries = tuple(
        SourceQuery(external_id=str(record["_id"]), text=str(record["text"]))
        for record in _read_json_lines(directory / "queries.jsonl")
        if str(record["_id"]) in selected_query_ids
    )
    return LoadedDataset(documents=documents, queries=queries, qrels=tuple(qrels))
