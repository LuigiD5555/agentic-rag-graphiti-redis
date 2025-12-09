"""Module for legacy Word and rich-text files loader."""
from typing import List

try:
    from langchain_core.documents import Document
except ImportError:  # pragma: no cover
    from langchain.schema import Document  # type: ignore

from langchain_community.document_loaders import (
    UnstructuredWordDocumentLoader as _Loader,
)


class WordLoader:
    """Word document loader for .doc/.docm/.rtf files."""

    def __init__(self, path: str):
        self.loader = _Loader(path)

    def load(self) -> List[Document]:
        """
        Load Word-based documents.

        Returns:
            List[Document]: Loaded documents.
        """
        return self.loader.load()
