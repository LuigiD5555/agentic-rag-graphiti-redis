"""Module for docx files loader."""
from __future__ import annotations

from typing import Callable, List
from zipfile import BadZipFile

try:
    from langchain_core.documents import Document
except ImportError:  # pragma: no cover
    from langchain.schema import Document  # type: ignore

from src.storage.vector.ingestion.loaders.errors import (
    LoaderInvalidFormatError,
    dependency_missing,
    ensure_file_exists,
)


class DocxLoader:
    """Docx document loader with a fallback that avoids docx2txt."""

    def __init__(self, path: str):
        self._path = path

    def load(self) -> List[Document]:
        """
        Load docx documents.

        Returns:
            List[Document]: Loaded documents.
        """
        ensure_file_exists(self._path)
        loader = self._get_loader()
        return loader()

    def _get_loader(self) -> Callable[[], List[Document]]:
        """Pick the best available loader implementation."""
        try:
            from langchain_community.document_loaders import Docx2txtLoader as _Loader
        except ImportError:  # pragma: no cover - langchain handles this
            return self._python_docx_loader

        try:
            import docx2txt  # noqa: F401
        except ImportError:  # pragma: no cover
            return self._python_docx_loader

        return lambda: _Loader(self._path).load()

    def _python_docx_loader(self) -> List[Document]:
        """Fallback loader that relies on python-docx."""
        try:
            from docx import Document as DocxDocument
            from docx.opc.exceptions import PackageNotFoundError
        except ImportError:  # pragma: no cover
            dependency_missing(
                "python-docx",
                "Install it to process .docx files when docx2txt is unavailable.",
            )
            raise  # unreachable, dependency_missing raises

        try:
            doc = DocxDocument(self._path)
        except (PackageNotFoundError, BadZipFile) as exc:
            return self._unstructured_loader(exc)

        lines: List[str] = []

        def _append(text: str) -> None:
            stripped = text.strip()
            if stripped:
                lines.append(stripped)

        for paragraph in doc.paragraphs:
            _append(paragraph.text)

        for table in doc.tables:
            for row in table.rows:
                row_values = []
                for cell in row.cells:
                    cell_text = cell.text.strip()
                    if cell_text:
                        row_values.append(cell_text)
                _append(" | ".join(row_values))

        return [
            Document(
                page_content="\n".join(lines),
                metadata={"source": self._path},
            )
        ]

    def _unstructured_loader(self, original_exc: Exception) -> List[Document]:
        """Fallback loader that leverages unstructured for oddball docx files."""
        try:
            from langchain_community.document_loaders import UnstructuredWordDocumentLoader
        except ImportError:  # pragma: no cover
            dependency_missing(
                "unstructured",
                "Required to process Word files that use a non-standard format.",
            )
            raise  # pragma: no cover

        try:
            return UnstructuredWordDocumentLoader(self._path).load()
        except ValueError as exc:
            plain = self._plain_text_fallback(exc)
            if plain:
                return plain
            raise LoaderInvalidFormatError(
                self._path,
                expected="DOCX",
                detail=str(exc),
            ) from original_exc

    def _plain_text_fallback(self, secondary_exc: Exception) -> List[Document]:
        """
        Last-resort fallback: attempt to read file bytes as text.

        Useful when a file is mislabeled as .docx but not a valid Zip/docx. We
        return an empty list if the content is unreadable to avoid crashing the
        pipeline.
        """
        try:
            with open(self._path, "rb") as handle:
                raw = handle.read()
        except OSError:
            return []

        text = raw.decode(errors="ignore").strip()
        if not text:
            return []

        return [
            Document(
                page_content=text,
                metadata={
                    "source": self._path,
                    "fallback": "plain_text",
                    "error": str(secondary_exc),
                },
            )
        ]
