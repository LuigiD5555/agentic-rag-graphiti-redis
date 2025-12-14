"""Module for plain text loader"""
from typing import List

from langchain_core.documents import Document

from langchain_community.document_loaders import TextLoader as _Loader


class PlainTextLoader:
    """Plain text loader class."""
    def __init__(self, path: str):
        self.loader = _Loader(path, encoding="utf-8")

    def load(self) -> List[Document]:
        """Load plain text documents.

        Returns:
            List[Document]: Loaded documents.
        """
        return self.loader.load()
