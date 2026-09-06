"""Base behavior for immutable boundary models."""

from pydantic import BaseModel, ConfigDict


class Contract(BaseModel):
    """Strict, immutable base class for public contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)
