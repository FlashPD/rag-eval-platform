"""BEIR dataset ingestion pipeline."""

from ragops.ingestion.loader import load_beir_dataset
from ragops.ingestion.service import IngestionService

__all__ = ["IngestionService", "load_beir_dataset"]
