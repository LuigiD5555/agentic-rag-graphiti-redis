"""Public interface for the ingestion pipeline package."""

from .pipeline import IngestionPipeline, SplitterStrategy

__all__ = ["IngestionPipeline", "SplitterStrategy"]
