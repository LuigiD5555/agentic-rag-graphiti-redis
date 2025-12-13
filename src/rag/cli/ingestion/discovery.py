"""Compatibility shim; use src.ingestion.cli.discovery instead."""

from src.ingestion.cli.discovery import FileDiscoveryService

__all__ = ["FileDiscoveryService"]
