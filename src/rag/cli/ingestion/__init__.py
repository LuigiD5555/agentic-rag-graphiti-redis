"""Compatibility shim for legacy imports; ingestion CLI now lives in src.ingestion.cli."""

from src.ingestion.cli import IngestionCLI, IngestionOrchestrator, FileDiscoveryService, normalize_extension, main

__all__ = ["IngestionCLI", "IngestionOrchestrator", "FileDiscoveryService", "normalize_extension", "main"]
