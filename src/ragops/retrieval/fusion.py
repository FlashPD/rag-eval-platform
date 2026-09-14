"""Transparent, deterministic rank fusion."""

from collections.abc import Sequence

from ragops.retrieval.types import StageHit


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[StageHit]], *, k: int = 60
) -> tuple[StageHit, ...]:
    if k <= 0:
        raise ValueError("RRF k must be positive")

    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            scores[hit.document_id] = scores.get(hit.document_id, 0.0) + 1.0 / (k + rank)
    return tuple(
        StageHit(document_id=document_id, score=score)
        for document_id, score in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    )
