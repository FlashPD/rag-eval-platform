"""Deterministic retrieval metrics computed from ranked document identifiers."""

from collections.abc import Mapping, Sequence
from math import log2

from ragops.contracts import RetrievalMetricScores

NDCG_CUTOFF = 10
RECALL_CUTOFFS = (10, 100)
MRR_CUTOFF = 10
RETRIEVAL_METRIC_NAMES = (
    "ndcg_at_10",
    "recall_at_10",
    "recall_at_100",
    "mrr_at_10",
)


def _validate_inputs(ranked_document_ids: Sequence[str], qrels: Mapping[str, int]) -> None:
    if len(set(ranked_document_ids)) != len(ranked_document_ids):
        raise ValueError("ranked document identifiers must be unique")
    negative_relevance = sorted(
        document_id for document_id, relevance in qrels.items() if relevance < 0
    )
    if negative_relevance:
        raise ValueError(
            f"qrel relevance must be nonnegative for documents: {', '.join(negative_relevance)}"
        )


def _discounted_cumulative_gain(relevances: Sequence[int]) -> float:
    # TREC nDCG uses the relevance grade as the gain and log2(rank + 1) as the discount.
    return sum(relevance / log2(rank + 1) for rank, relevance in enumerate(relevances, start=1))


def _ndcg_at(
    ranked_document_ids: Sequence[str],
    qrels: Mapping[str, int],
    *,
    cutoff: int,
) -> float:
    observed_relevance = [qrels.get(document_id, 0) for document_id in ranked_document_ids[:cutoff]]
    ideal_relevance = sorted(
        (relevance for relevance in qrels.values() if relevance > 0), reverse=True
    )[:cutoff]
    ideal_gain = _discounted_cumulative_gain(ideal_relevance)
    if ideal_gain == 0:
        return 0.0
    return _discounted_cumulative_gain(observed_relevance) / ideal_gain


def _recall_at(
    ranked_document_ids: Sequence[str],
    qrels: Mapping[str, int],
    *,
    cutoff: int,
) -> float:
    relevant_document_ids = {
        document_id for document_id, relevance in qrels.items() if relevance > 0
    }
    if not relevant_document_ids:
        return 0.0
    retrieved_relevant = relevant_document_ids.intersection(ranked_document_ids[:cutoff])
    return len(retrieved_relevant) / len(relevant_document_ids)


def _reciprocal_rank_at(
    ranked_document_ids: Sequence[str],
    qrels: Mapping[str, int],
    *,
    cutoff: int,
) -> float:
    for rank, document_id in enumerate(ranked_document_ids[:cutoff], start=1):
        if qrels.get(document_id, 0) > 0:
            return 1.0 / rank
    return 0.0


def compute_retrieval_metrics(
    ranked_document_ids: Sequence[str],
    qrels: Mapping[str, int],
) -> RetrievalMetricScores:
    """Compute the platform's four retrieval metrics for one query.

    Positive qrel grades are relevant for recall and reciprocal rank. nDCG preserves
    graded relevance. Queries without a positively relevant document receive zero for
    every metric, matching the evaluation runner's explicit zero-score policy.
    """
    _validate_inputs(ranked_document_ids, qrels)
    return RetrievalMetricScores(
        ndcg_at_10=_ndcg_at(ranked_document_ids, qrels, cutoff=NDCG_CUTOFF),
        recall_at_10=_recall_at(ranked_document_ids, qrels, cutoff=RECALL_CUTOFFS[0]),
        recall_at_100=_recall_at(ranked_document_ids, qrels, cutoff=RECALL_CUTOFFS[1]),
        mrr_at_10=_reciprocal_rank_at(ranked_document_ids, qrels, cutoff=MRR_CUTOFF),
    )
