import pytest

from ragops.retrieval.fusion import reciprocal_rank_fusion
from ragops.retrieval.types import StageHit


def test_rrf_matches_hand_computed_scores_and_breaks_ties_by_identifier() -> None:
    first = (
        StageHit(document_id="a", score=10),
        StageHit(document_id="b", score=9),
    )
    second = (
        StageHit(document_id="b", score=1),
        StageHit(document_id="c", score=0.5),
    )

    fused = reciprocal_rank_fusion((first, second), k=60)

    assert [hit.document_id for hit in fused] == ["b", "a", "c"]
    assert fused[0].score == pytest.approx(1 / 62 + 1 / 61)
    assert fused[1].score == pytest.approx(1 / 61)
    assert fused[2].score == pytest.approx(1 / 62)


def test_rrf_handles_documents_present_in_only_one_ranking() -> None:
    fused = reciprocal_rank_fusion(
        ((StageHit(document_id="only", score=1),), ()),
        k=1,
    )

    assert fused == (StageHit(document_id="only", score=0.5),)
