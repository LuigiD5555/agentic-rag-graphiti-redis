"""Module for OpenDocument files loader."""
from pathlib import Path
from typing import List

from langchain_core.documents import Document

from langchain_community.document_loaders import UnstructuredFileLoader as _Loader
from unstructured.partition.common import UnsupportedFileFormatError

from src.ingestion.loaders.errors import LoaderInvalidFormatError, ensure_file_exists


class OpenDocumentLoader:
    """OpenDocument text/spreadsheet/presentation loader."""

    def __init__(self, path: str):
        # UnstructuredFileLoader detects ODF types automatically.
        self.path = path
        ensure_file_exists(path)
        ext = Path(path).suffix.lower()
        allowed_exts = {".odt", ".ods", ".odp"}
        if ext and ext not in allowed_exts:
            raise LoaderInvalidFormatError(path, "OpenDocument (.odt/.ods/.odp)")
        self.loader = _Loader(path)

    def load(self) -> List[Document]:
        """
        Load OpenDocument files.

        Returns:
            List[Document]: Loaded documents.
        """
        try:
            return self.loader.load()
        except UnsupportedFileFormatError as exc:
            raise LoaderInvalidFormatError(
                self.path,
                "OpenDocument (.odt/.ods/.odp)",
                detail=str(exc),
            ) from exc
