"""
Object-oriented CLI to ingest documents and code into a vector database using embeddings.

This module lives under src.rag.cli to centralize CLI-related logic.
"""

import argparse

from .helpers import build_ingestion_options_from_args
from src.rag.ingestion.orchestrator import IngestionOrchestrator
from src.rag.audit import configure_logging, get_logger, resolve_level
from src.rag.conf import Config


class IngestionCLI:
    """CLI facade that parses arguments, configures logging, and executes the orchestrator."""

    def __init__(self) -> None:
        self._config = Config()
        self._parser = self._build_parser()
        self._log = get_logger(__name__)

    def run(self) -> None:
        """Parse CLI args, configure logging, build options, and run ingestion."""
        args = self._parser.parse_args()
        self._configure_logging(args.log_level)
        options = build_ingestion_options_from_args(args, self._config)
        IngestionOrchestrator(self._config).run(options)

    def _build_parser(self) -> argparse.ArgumentParser:
        """Create and return the ArgumentParser configured for this CLI."""
        parser = argparse.ArgumentParser(description="Ingest documents and code into a vector DB.")
        parser.add_argument(
            "paths",
            nargs="*",
            help="Root directories or files. If omitted, uses DOCS_PATHS from settings/.env.",
        )
        parser.add_argument(
            "--exts",
            nargs="+",
            default=None,
            help="Extensions to include (e.g., .md .pdf .txt). If omitted, uses DOCS_FILE_EXTS from .env.",
        )
        parser.add_argument(
            "--exclude-dirs",
            nargs="+",
            default=None,
            help="Directory NAMES to exclude (e.g., .git node_modules __pycache__).",
        )
        parser.add_argument(
            "--exclude-patterns",
            nargs="+",
            default=None,
            help="Glob patterns (relative paths) to exclude, e.g. '*.log' 'data/cache/*'.",
        )
        parser.add_argument(
            "--follow-symlinks",
            action="store_true",
            help="Follow symlinks while scanning.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only list what would be ingested; do not call the pipeline.",
        )
        parser.add_argument(
            "--per-file",
            action="store_true",
            help="Ingest one file at a time (more logs, slower). Default is batch.",
        )
        parser.add_argument(
            "--max-files",
            type=int,
            default=0,
            help="Limit the number of files to ingest (0 = no limit).",
        )
        parser.add_argument(
            "--scan-progress",
            type=int,
            default=0,
            help="Log a progress line every N visited directories during scan (0 = disabled).",
        )
        parser.add_argument(
            "--log-level",
            default=None,
            help="Python log level (DEBUG, INFO, WARNING, ERROR). Defaults to .env INGEST_LOG_LEVEL or INFO.",
        )
        return parser

    def _configure_logging(self, level_from_cli: str | None) -> None:
        """Configure basic logging using CLI or .env fallback."""
        log_level_name = (level_from_cli or getattr(self._config, "INGEST_LOG_LEVEL", "INFO") or "INFO").upper()
        level_value = resolve_level(log_level_name)
        configure_logging(level_value, fmt="%(levelname)s: %(message)s")
        self._log.debug("Logging configured at level=%s", log_level_name)

def main() -> None:
    """Entrypoint for `python -m src.main --ingest ...`."""
    IngestionCLI().run()


__all__ = ["IngestionCLI", "main"]


if __name__ == "__main__":
    main()
