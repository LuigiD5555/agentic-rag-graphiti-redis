"""Compatibility shim; use src.ingestion.cli.cli instead."""

from src.ingestion.cli.cli import IngestionCLI, main

__all__ = ["IngestionCLI", "main"]


if __name__ == "__main__":  # pragma: no cover
    main()
