"""CLI helpers for ingestion, centralized under src.ingestion."""

from .cli import IngestionCLI, main
from .helpers import normalize_extension

__all__ = ["IngestionCLI", "normalize_extension", "main"]
