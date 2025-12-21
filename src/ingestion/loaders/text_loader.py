"""Module for plain text loader."""
from typing import List

from langchain_core.documents import Document

from src.ingestion.loaders.errors import LoaderUnreadableTextError, ensure_file_exists
from src.ingestion.pipeline.utils.text_reading import read_text_with_fallbacks


class PlainTextLoader:
    """Plain text loader class."""
    def __init__(self, path: str):
        self.path = path

    def load(self) -> List[Document]:
        """Load plain text documents.

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

        return [Document(page_content=result.text, metadata={"source": self.path, "encoding": result.encoding})]
