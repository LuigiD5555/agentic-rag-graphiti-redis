"""
Object-oriented CLI to ingest documents and code into a vector database using embeddings.

Design goals:
- Clear separation of concerns:
  * IngestionOptions          -> Pure configuration container
  * FileDiscoveryService      -> Filesystem scanning and filtering
  * IngestionOrchestrator     -> Wires services and runs ingestion
  * IngestionCLI              -> CLI facade (argparse + logging)
- Auditable logs and robust defaults.

Usage examples:
    # Use directories from .env/settings (DOCS_PATHS)
    python -m src.main --ingest

    # Explicit roots and custom extensions
    python -m src.main --ingest /mnt/Documents/Documents /mnt/MoreDocs --exts .md .pdf .txt

    # Dry-run (only list what would be ingested)
    python -m src.main --ingest /data/docs --dry-run --log-level DEBUG
"""

from src.ingestion.discovery import FileDiscoveryService
from src.ingestion import IngestionCLI
from src.ingestion.orchestrator import IngestionOrchestrator
from src.ingestion.cli import main as _ingestion_main


__all__ = ["FileDiscoveryService", "IngestionCLI", "IngestionOrchestrator", "main"]


def main() -> None:
    """Entrypoint for `python -m src.main --ingest ...`."""
    _ingestion_main()


if __name__ == "__main__":
    main()
