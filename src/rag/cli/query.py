"""Compatibility shim; the ingestion CLI now lives in src.ingestion.cli.query."""

from src.ingestion.cli.query import main

__all__ = ["main"]


if __name__ == "__main__":  # pragma: no cover
    main()
