"""Module for CSV files loader."""
from typing import List

try:
    from langchain_core.documents import Document
except ImportError:  # pragma: no cover
    from langchain.schema import Document  # type: ignore

from langchain_community.document_loaders import CSVLoader as _Loader


class CSVLoader:
    """CSV document loader."""

    def __init__(self, path: str):
        self.loader = _Loader(file_path=path)

    def load(self) -> List[Document]:
        """
        Load CSV documents.

        Returns:
            List[Document]: Loaded documents.
        """
        return self.loader.load()
