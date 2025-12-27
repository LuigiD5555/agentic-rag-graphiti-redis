"""Module for OpenDocument files loader."""
from pathlib import Path
from typing import List

from langchain_core.documents import Document

from src.ingestion.loaders.errors import LoaderInvalidFormatError, ensure_file_exists
from src.ingestion.loaders.office_client import OfficeToolClient


class OpenDocumentLoader:
    """OpenDocument text/spreadsheet/presentation loader.

    Uses rag-tool-office HTTP service for conversion (LibreOffice backend).
    """

    def __init__(self, path: str):
        self.path = path
        self._client = OfficeToolClient()
        ensure_file_exists(path)
        ext = Path(path).suffix.lower()
        allowed_exts = {".odt", ".ods", ".odp"}
        if ext and ext not in allowed_exts:
            raise LoaderInvalidFormatError(path, "OpenDocument (.odt/.ods/.odp)")

    def load(self) -> List[Document]:
        """
        Load OpenDocument files via rag-tool-office.

        Returns:
            List[Document]: Loaded documents.
        """
        try:
            doc = self._client.load_as_document(self.path)
            return [doc]
        except RuntimeError as exc:
            raise LoaderInvalidFormatError(
                self.path,
                "OpenDocument (.odt/.ods/.odp)",
                detail=str(exc),
            ) from exc
