"""Module for PowerPoint files loader."""
from typing import List

try:
    from langchain_core.documents import Document
except ImportError:  # pragma: no cover
    from langchain.schema import Document  # type: ignore

from langchain_community.document_loaders import (
    UnstructuredPowerPointLoader as _Loader,
)
from pptx.exc import PackageNotFoundError

from src.storage.vector.ingestion.loaders.errors import LoaderInvalidFormatError, ensure_file_exists


class PowerPointLoader:
    """PowerPoint document loader."""

    def __init__(self, path: str):
        self._path = path

    def load(self) -> List[Document]:
        """
        Load PowerPoint documents.

        Returns:
            List[Document]: Loaded documents.
        """
        ensure_file_exists(self._path)
        loader = _Loader(self._path)
        try:
            return loader.load()
        except (PackageNotFoundError, ValueError) as exc:
            # PackageNotFoundError is raised for missing/corrupt files; present
            # as an invalid format to avoid crashing the pipeline.
            raise LoaderInvalidFormatError(
                self._path,
                expected="PPTX",
                detail=str(exc),
            ) from exc
