"""Module for Excel files loader."""
from typing import List
from zipfile import BadZipFile

try:
    from langchain_core.documents import Document
except ImportError:  # pragma: no cover
    from langchain.schema import Document  # type: ignore

from langchain_community.document_loaders import UnstructuredExcelLoader as _Loader
from unstructured.errors import UnprocessableEntityError

from src.ingestion.loaders.errors import (
    LoaderDependencyError,
    LoaderInvalidFormatError,
    ensure_file_exists,
)

try:  # pragma: no cover - optional dependency, handled defensively
    from msoffcrypto.exceptions import FileFormatError as _CryptoFileFormatError
except Exception:  # pragma: no cover - broad by design to catch missing dependency
    _CryptoFileFormatError = None


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
        except Exception as exc:  # pragma: no cover - guarded to keep TypeErrors visible
            if _CryptoFileFormatError and isinstance(exc, _CryptoFileFormatError):
                raise LoaderInvalidFormatError(self._path, expected="XLSX", detail=str(exc)) from exc
            raise
