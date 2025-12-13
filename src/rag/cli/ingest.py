"""Backward-compatible entry point for `python -m src.rag.cli.ingest`."""

from src.ingestion.cli.cli import main


if __name__ == "__main__":
    main()
