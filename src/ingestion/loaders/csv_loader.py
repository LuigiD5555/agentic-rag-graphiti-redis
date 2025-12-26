"""Module for CSV files loader."""
import os
from typing import List

from langchain_core.documents import Document

from langchain_community.document_loaders import CSVLoader as _Loader

from src.rag.audit import get_logger

log = get_logger(__name__)


class CSVLoader:
    """CSV document loader with row limit to prevent memory issues."""

    # Maximum rows to load from a CSV file (prevents OOM on huge CSVs)
    MAX_ROWS = 50000
    # Maximum file size in bytes (150 MB) before applying stricter limits
    MAX_FILE_SIZE_BYTES = 150 * 1024 * 1024

    def __init__(self, path: str):
        self._path = path
        # Specify UTF-8 encoding explicitly for multilingual support
        self.loader = _Loader(file_path=path, encoding='utf-8')

    def load(self) -> List[Document]:
        """
        Load CSV documents with row limit protection.

        For very large CSV files (>150MB), applies a row limit to prevent
        memory exhaustion. Each row becomes a separate Document, so a CSV
        with millions of rows would create millions of Document objects.

        Returns:
            List[Document]: Loaded documents (limited to MAX_ROWS if needed).
        """
        # Check file size
        file_size = os.path.getsize(self._path)

        if file_size > self.MAX_FILE_SIZE_BYTES:
            log.warning(
                "Large CSV detected: %s (%.1f MB). This may take a while or hit row limits.",
                os.path.basename(self._path),
                file_size / (1024 * 1024)
            )

        # Load documents
        documents = self.loader.load()

        # Apply row limit if exceeded
        if len(documents) > self.MAX_ROWS:
            log.warning(
                "CSV truncated from %d to %d rows to prevent memory issues: %s",
                len(documents),
                self.MAX_ROWS,
                os.path.basename(self._path)
            )
            documents = documents[:self.MAX_ROWS]

        return documents
