"""Internal typed values exchanged by retrieval stages."""

from pydantic import Field

from ragops.contracts.base import Contract


class StageHit(Contract):
    document_id: str = Field(min_length=1)
    score: float
