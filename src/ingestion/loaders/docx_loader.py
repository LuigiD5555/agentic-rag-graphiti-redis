"""Module for docx files loader."""
from typing import List

try:
    from langchain_core.documents import Document
except ImportError:  # pragma: no cover
    from langchain.schema import Document  # type: ignore

from langchain_community.document_loaders import Docx2txtLoader as _Loader


class DocxLoader:
    """Docx document loader."""
    def __init__(self, path: str):
        self.loader = _Loader(path)

    def load(self) -> List[Document]:
        """
        Load docx documents.

        Returns:
            List[Document]: Loaded documents.
        """
        return self.loader.load()
