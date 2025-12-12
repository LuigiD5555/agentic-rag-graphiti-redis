"""Public interface for the ingestion pipeline package."""

from .core import IngestionPipeline, SplitterStrategy

__all__ = ["IngestionPipeline", "SplitterStrategy"]
