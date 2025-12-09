"""Backward-compatible entry point for `python -m src.cli.ingest`."""

from src.cli.ingestion.cli import main


if __name__ == "__main__":
    main()
