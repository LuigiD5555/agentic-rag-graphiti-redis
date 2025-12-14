"""Module for email message loaders (.eml/.msg)."""
from typing import List

from langchain_core.documents import Document

from langchain_community.document_loaders import (
    OutlookMessageLoader,
    UnstructuredEmailLoader,
)


class EmailLoader:
    """Email loader that supports .eml and .msg formats."""

    def __init__(self, path: str):
        self.path = path
        self.loader = self._select_loader(path)

    def load(self) -> List[Document]:
        """
        Load email documents.

        Returns:
            List[Document]: Loaded documents.
        """
        return self.loader.load()

    @staticmethod
    def _select_loader(path: str):
        if path.lower().endswith(".eml"):
            return UnstructuredEmailLoader(file_path=path)

        if path.lower().endswith(".msg"):
            return OutlookMessageLoader(file_path=path)

        # Fallback: attempt generic email loader even if extension is uncommon.
        return UnstructuredEmailLoader(file_path=path)
