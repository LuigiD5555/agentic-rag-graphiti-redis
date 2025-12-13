"""Module for legacy Word and rich-text files loader."""
from __future__ import annotations

from typing import List

try:
    from langchain_core.documents import Document
except ImportError:  # pragma: no cover
    from langchain.schema import Document  # type: ignore

from src.storage.vector.ingestion.loaders.errors import (
    LoaderInvalidFormatError,
    dependency_missing,
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

        try:
            from langchain_community.document_loaders import (
                UnstructuredWordDocumentLoader as _Loader,
            )
        except ImportError:
            dependency_missing(
                "unstructured",
                "Required to process legacy Word files.",
            )
            raise  # pragma: no cover

        loader = _Loader(self._path)

        try:
            return loader.load()
        except ValueError as exc:
            raise LoaderInvalidFormatError(
                self._path,
                expected="Word (.doc, .docm, .rtf)",
                detail=str(exc),
            ) from exc
