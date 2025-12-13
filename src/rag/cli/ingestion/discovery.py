"""Compatibility shim; discovery now lives in src.ingestion.discovery."""

from src.ingestion.discovery import FileDiscoveryService

__all__ = ["FileDiscoveryService"]
