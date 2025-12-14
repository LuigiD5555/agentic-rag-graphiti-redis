"""Module for markdown file loader"""
from typing import List
import re

from langchain_core.documents import Document

from langchain_community.document_loaders import TextLoader as _Loader


class MarkdownLoader:
    """Loader for markdown files."""
    def __init__(self, path: str):
        self.loader = _Loader(path, encoding="utf-8")

    def _clean(self, text: str) -> str:
        text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        return text

    def load(self) -> List[Document]:
        """
        This method removes images and links from the markdown content.

        Returns:
            List[Document]: Loaded documents.
        """
        documents = self.loader.load()
        for doc in documents:
            doc.page_content = self._clean(doc.page_content)
        return documents
