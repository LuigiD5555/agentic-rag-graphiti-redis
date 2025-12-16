"""Ingestion module for RAG - handles document loading, processing, and indexing."""

from .cli import IngestionCLI, main
from .orchestrator import IngestionOrchestrator
from .discovery import FileDiscoveryService
from .options import DiscoveryOptions, IngestionOptions, PipelineOptions
from .pipeline import IngestionPipeline

__all__ = [
    "IngestionCLI",
    "main",
    "IngestionOrchestrator",
    "FileDiscoveryService",
    "DiscoveryOptions",
    "IngestionOptions",
    "PipelineOptions",
    "IngestionPipeline",
]
