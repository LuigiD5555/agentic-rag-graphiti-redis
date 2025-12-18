"""Module for Excel files loader."""
from typing import List
from zipfile import BadZipFile

from langchain_core.documents import Document

from langchain_community.document_loaders import UnstructuredExcelLoader as _Loader
from unstructured.errors import UnprocessableEntityError

from src.ingestion.loaders.errors import (
    LoaderDependencyError,
    LoaderInvalidFormatError,
    ensure_file_exists,
)

from msoffcrypto.exceptions import FileFormatError as _CryptoFileFormatError


class ExcelLoader:
    """Excel document loader."""

    def __init__(self, path: str):
        self._path = path

    def load(self) -> List[Document]:
        """
        Load Excel documents.

        Returns:
            List[Document]: Loaded documents.
        """
        ensure_file_exists(self._path)
        loader = _Loader(self._path)

        try:
            return loader.load()
        except ImportError as exc:
            # Pandas requires xlrd for legacy .xls files. Surface this as a friendly dependency error.
            if "xlrd" in str(exc).lower():
                raise LoaderDependencyError(
                    "xlrd>=2.0.1", "Install to enable .xls Excel ingestion."
                ) from exc
            raise
        except UnprocessableEntityError as exc:
            raise LoaderInvalidFormatError(self._path, expected="XLSX", detail=str(exc)) from exc
        except BadZipFile as exc:
            raise LoaderInvalidFormatError(self._path, expected="XLSX", detail=str(exc)) from exc
        except _CryptoFileFormatError as exc:  # pragma: no cover
            raise LoaderInvalidFormatError(self._path, expected="XLSX", detail=str(exc)) from exc
