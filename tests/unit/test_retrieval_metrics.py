from math import log2

import pytest

from ragops.contracts import RetrievalMetricScores
from ragops.evaluation import compute_retrieval_metrics


def test_perfect_ranking_scores_one_for_every_metric() -> None:
    scores = compute_retrieval_metrics(
        ("doc-high", "doc-medium", "doc-low"),
        {"doc-high": 3, "doc-medium": 2, "doc-low": 1},
    )

    assert scores == RetrievalMetricScores(
        ndcg_at_10=1.0,
        recall_at_10=1.0,
        recall_at_100=1.0,
        mrr_at_10=1.0,
    )


def test_ndcg_preserves_graded_relevance_and_rank_discount() -> None:
    scores = compute_retrieval_metrics(
        ("doc-medium", "doc-high", "irrelevant"),
        {"doc-high": 3, "doc-medium": 2, "unretrieved": 0},
    )
    expected_dcg = 2 + 3 / log2(3)
    ideal_dcg = 3 + 2 / log2(3)

    assert scores.ndcg_at_10 == pytest.approx(expected_dcg / ideal_dcg)
    assert scores.recall_at_10 == 1.0
    assert scores.mrr_at_10 == 1.0


def test_recall_uses_10_and_100_document_cutoffs() -> None:
    relevant_ids = tuple(f"relevant-{index}" for index in range(1, 12))

    scores = compute_retrieval_metrics(relevant_ids, dict.fromkeys(relevant_ids, 1))

    assert scores.recall_at_10 == pytest.approx(10 / 11)
    assert scores.recall_at_100 == 1.0


def test_mrr_ignores_first_relevant_document_after_rank_10() -> None:
    ranking = (*tuple(f"irrelevant-{index}" for index in range(10)), "relevant")

    scores = compute_retrieval_metrics(ranking, {"relevant": 1})

    assert scores.mrr_at_10 == 0.0
    assert scores.recall_at_10 == 0.0
    assert scores.recall_at_100 == 1.0


def test_zero_grade_and_empty_qrels_produce_zero_scores() -> None:
    zero_grade = compute_retrieval_metrics(("document",), {"document": 0})
    no_qrels = compute_retrieval_metrics(("document",), {})

    assert zero_grade == RetrievalMetricScores(
        ndcg_at_10=0.0,
        recall_at_10=0.0,
        recall_at_100=0.0,
        mrr_at_10=0.0,
    )
    assert no_qrels == zero_grade


def test_duplicate_ranked_documents_are_rejected() -> None:
    with pytest.raises(ValueError, match="must be unique"):
        compute_retrieval_metrics(("duplicate", "duplicate"), {"duplicate": 1})


def test_negative_qrel_relevance_is_rejected() -> None:
    with pytest.raises(ValueError, match="must be nonnegative"):
        compute_retrieval_metrics(("document",), {"document": -1})


def test_scores_convert_to_query_result_storage_shape() -> None:
    scores = compute_retrieval_metrics(("relevant",), {"relevant": 1})

    assert scores.as_score_dict() == {
        "ndcg_at_10": 1.0,
        "recall_at_10": 1.0,
        "recall_at_100": 1.0,
        "mrr_at_10": 1.0,
    }
