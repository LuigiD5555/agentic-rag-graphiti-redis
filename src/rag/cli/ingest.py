"""Backward-compatible entry point for `python -m src.rag.cli.ingest`."""

from src.rag.cli.ingestion.cli import main


if __name__ == "__main__":
    main()
