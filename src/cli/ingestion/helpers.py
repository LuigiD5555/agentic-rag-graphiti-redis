"""Shared helper utilities for the ingestion CLI."""

def normalize_extension(ext: str) -> str:
    """Normalize a CLI extension entry to lowercase and ensure it starts with a dot."""
    normalized = ext.strip().lower()
    return normalized if normalized.startswith(".") else f".{normalized}"
