"""Module for markdown file loader."""
from typing import List
import re

from langchain_core.documents import Document

from src.ingestion.loaders.errors import LoaderUnreadableTextError, ensure_file_exists
from src.utils.text_reading import read_text_with_fallbacks


class MarkdownLoader:
    """Loader for markdown files."""
    def __init__(self, path: str):
        self.path = path

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
        ensure_file_exists(self.path)
        try:
            result = read_text_with_fallbacks(self.path)
        except ValueError as exc:
            raise LoaderUnreadableTextError(self.path, str(exc)) from exc
        except UnicodeDecodeError as exc:
            raise LoaderUnreadableTextError(self.path, str(exc)) from exc

        cleaned = self._clean(result.text)
        return [Document(page_content=cleaned, metadata={"source": self.path, "encoding": result.encoding})]
