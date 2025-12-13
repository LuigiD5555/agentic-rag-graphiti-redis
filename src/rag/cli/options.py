"""Compatibility shim; ingestion options now live in src.ingestion.options."""

from src.ingestion.options import DiscoveryOptions, IngestionOptions, PipelineOptions

__all__ = ["DiscoveryOptions", "IngestionOptions", "PipelineOptions"]
