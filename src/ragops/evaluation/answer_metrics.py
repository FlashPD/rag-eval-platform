"""Deterministic answer and SciFact verification metrics."""

from collections.abc import Mapping, Sequence

from ragops.contracts import AnswerMetricScores, AnswerResponse, SciFactLabel


def compute_answer_metrics(
    answer: AnswerResponse,
    qrels: Mapping[str, int],
) -> AnswerMetricScores:
    """Score citations, retrieved-context precision, and correct abstention."""
    relevant = {document_id for document_id, relevance in qrels.items() if relevance > 0}
    retrieved = {passage.document_id for passage in answer.contexts}
    context_precision = len(relevant & retrieved) / len(retrieved) if retrieved else 0.0
    has_relevant_context = bool(relevant & retrieved)
    expected_abstention = not has_relevant_context
    return AnswerMetricScores(
        citation_validity=float(
            answer.citation_validation is not None and answer.citation_validation.valid
        ),
        context_precision=context_precision,
        abstention_correctness=float(answer.abstained == expected_abstention),
    )


def scifact_gold_label(metadata: Mapping[str, object]) -> SciFactLabel:
    """Read a SciFact label from its original BEIR-preserved evidence metadata."""
    if not metadata:
        return SciFactLabel.NOT_ENOUGH_INFO
    labels: set[str] = set()
    for rationales in metadata.values():
        if not isinstance(rationales, list):
            raise ValueError("SciFact evidence metadata must contain rationale lists")
        for rationale in rationales:
            if not isinstance(rationale, dict) or not isinstance(rationale.get("label"), str):
                raise ValueError("SciFact rationale metadata is missing a label")
            labels.add(rationale["label"])
    if len(labels) != 1:
        raise ValueError(f"SciFact claim must have one consistent label, found {sorted(labels)}")
    return SciFactLabel(next(iter(labels)))


def compute_scifact_rationale_precision(
    answer: AnswerResponse,
    metadata: Mapping[str, object],
) -> float:
    """Measure predicted document/sentence rationale pairs against gold evidence."""
    local_to_document = {passage.local_id: passage.document_id for passage in answer.contexts}
    predicted = {
        (local_to_document[local_id], sentence)
        for local_id, sentences in answer.rationale_sentences.items()
        if local_id in local_to_document
        for sentence in sentences
    }
    gold: set[tuple[str, int]] = set()
    for document_id, rationales in metadata.items():
        if not isinstance(rationales, list):
            raise ValueError("SciFact evidence metadata must contain rationale lists")
        for rationale in rationales:
            if not isinstance(rationale, dict) or not isinstance(rationale.get("sentences"), list):
                raise ValueError("SciFact rationale metadata is missing sentence indices")
            gold.update((document_id, int(sentence)) for sentence in rationale["sentences"])
    if not predicted:
        return 1.0 if not gold else 0.0
    return len(predicted & gold) / len(predicted)


def macro_f1(
    gold: Sequence[SciFactLabel],
    predicted: Sequence[SciFactLabel | None],
) -> float:
    """Compute unweighted three-class F1, counting missing predictions as misses."""
    if not gold or len(gold) != len(predicted):
        raise ValueError("macro-F1 requires equal non-empty gold and prediction sequences")
    scores: list[float] = []
    for label in SciFactLabel:
        true_positive = sum(g == label and p == label for g, p in zip(gold, predicted, strict=True))
        false_positive = sum(
            g != label and p == label for g, p in zip(gold, predicted, strict=True)
        )
        false_negative = sum(
            g == label and p != label for g, p in zip(gold, predicted, strict=True)
        )
        denominator = 2 * true_positive + false_positive + false_negative
        scores.append((2 * true_positive / denominator) if denominator else 0.0)
    return sum(scores) / len(scores)
