from typing import List

from pypdf.errors import PdfReadError, PdfStreamError

from langchain_core.documents import Document

from langchain_community.document_loaders import PyPDFLoader as _Loader

from src.storage.vector.ingestion.loaders.errors import LoaderInvalidFormatError, ensure_file_exists


class PDFLoader:
    """PDF document loader."""
    def __init__(self, path: str):
        self._path = path
        self.loader = _Loader(path)

    def load(self) -> List[Document]:
        """
        Load PDF documents.

        Return: List[Document]
        """
        ensure_file_exists(self._path)
        try:
            return self.loader.load()
        except (PdfReadError, PdfStreamError, ValueError) as exc:
            raise LoaderInvalidFormatError(
                self._path,
                expected="PDF",
                detail=str(exc),
            ) from exc
