"""Module for OpenDocument files loader."""
from typing import List

try:
    from langchain_core.documents import Document
except ImportError:  # pragma: no cover
    from langchain.schema import Document  # type: ignore

from langchain_community.document_loaders import UnstructuredFileLoader as _Loader


class OpenDocumentLoader:
    """OpenDocument text/spreadsheet/presentation loader."""

    def __init__(self, path: str):
        # UnstructuredFileLoader detects ODF types automatically.
        self.loader = _Loader(path)

    def load(self) -> List[Document]:
        """
        Load OpenDocument files.

        Returns:
            List[Document]: Loaded documents.
        """
        return self.loader.load()
