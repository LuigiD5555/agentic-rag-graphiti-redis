"""Module for legacy Word and rich-text files loader."""
from typing import List

from langchain_core.documents import Document
from langchain_community.document_loaders import UnstructuredWordDocumentLoader

from src.ingestion.loaders.errors import (
    LoaderInvalidFormatError,
    ensure_file_exists,
)


class WordLoader:
    """Word document loader for .doc/.docm/.rtf files."""

    def __init__(self, path: str):
        self._path = path

    def load(self) -> List[Document]:
        """
        Load Word-based documents.

        Returns:
            List[Document]: Loaded documents.
        """
        ensure_file_exists(self._path)

        loader = UnstructuredWordDocumentLoader(self._path)

        try:
            return loader.load()
        except ValueError as exc:
            raise LoaderInvalidFormatError(
                self._path,
                expected="Word (.doc, .docm, .rtf)",
                detail=str(exc),
            ) from exc
