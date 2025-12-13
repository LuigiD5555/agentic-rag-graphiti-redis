"""Compatibility shim to run `python -m src.rag.cli.ingestion`."""

from src.ingestion.cli.__main__ import main

if __name__ == "__main__":  # pragma: no cover
    main()
