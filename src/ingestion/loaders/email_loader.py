"""Module for email message loaders (.eml/.msg)."""
from typing import List

try:
    from langchain_core.documents import Document
except ImportError:  # pragma: no cover
    from langchain.schema import Document  # type: ignore

from langchain_community.document_loaders import (
    UnstructuredEmailLoader,
)

try:  # Outlook loader may be optional.
    from langchain_community.document_loaders import OutlookMessageLoader
except ImportError:  # pragma: no cover
    OutlookMessageLoader = None  # type: ignore


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

        if path.lower().endswith(".msg") and OutlookMessageLoader is not None:
            return OutlookMessageLoader(file_path=path)

        # Fallback: attempt generic email loader even if extension is uncommon.
        return UnstructuredEmailLoader(file_path=path)
