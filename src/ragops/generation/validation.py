"""Deterministic validation for citations in structured answers."""

from collections.abc import Sequence

from ragops.contracts import CitationValidation, CitedAnswer, Passage


def _duplicates(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return tuple(duplicates)


def validate_citations(
    answer: CitedAnswer,
    contexts: Sequence[Passage],
) -> CitationValidation:
    """Check citation identity and answer consistency without repairing output.

    Context identifiers must be unique because an ambiguous identifier is a
    caller-side contract violation. Model-side problems are returned as a typed
    report so the answer pipeline can persist a ``citation_error`` outcome.
    """

    context_ids = tuple(context.local_id for context in contexts)
    duplicate_context_ids = _duplicates(context_ids)
    if duplicate_context_ids:
        raise ValueError(f"context local IDs must be unique: {duplicate_context_ids}")

    known_ids = set(context_ids)
    unknown = tuple(
        dict.fromkeys(citation for citation in answer.citations if citation not in known_ids)
    )
    duplicates = _duplicates(answer.citations)
    missing_inline = tuple(
        dict.fromkeys(citation for citation in answer.citations if citation not in answer.answer)
    )
    missing_required = not answer.abstained and not answer.citations
    citations_on_abstention = answer.abstained and bool(answer.citations)
    valid = not (
        unknown or duplicates or missing_inline or missing_required or citations_on_abstention
    )
    return CitationValidation(
        valid=valid,
        unknown_citations=unknown,
        duplicate_citations=duplicates,
        missing_inline_citations=missing_inline,
        missing_required_citation=missing_required,
        citations_on_abstention=citations_on_abstention,
    )
