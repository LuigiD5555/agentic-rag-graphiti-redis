"""Module for legacy Word and rich-text files loader."""
from typing import List

from langchain_core.documents import Document

from src.ingestion.loaders.errors import (
    LoaderInvalidFormatError,
    ensure_file_exists,
)
from src.ingestion.loaders.office_client import OfficeToolClient


class WordLoader:
    """Word document loader for .doc/.docm/.rtf files.

    Uses rag-tool-office HTTP service for conversion (LibreOffice backend).
    """

    def __init__(self, path: str):
        self._path = path
        self._client = OfficeToolClient()

    def load(self) -> List[Document]:
        """
        Load Word-based documents via rag-tool-office.

        Returns:
            List[Document]: Loaded documents.
        """
        ensure_file_exists(self._path)

        try:
            doc = self._client.load_as_document(self._path)
            return [doc]
        except RuntimeError as exc:
            raise LoaderInvalidFormatError(
                self._path,
                expected="Word (.doc, .docm, .rtf)",
                detail=str(exc),
            ) from exc
