"""Compatibility shim; use src.ingestion.cli.orchestrator instead."""

from src.ingestion.cli.orchestrator import IngestionOrchestrator

__all__ = ["IngestionOrchestrator"]
