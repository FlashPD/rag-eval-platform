"""Shared service schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthResponse(BaseModel):
    """Liveness response returned by the API."""

    model_config = ConfigDict(frozen=True)

    status: Literal["ok"]
