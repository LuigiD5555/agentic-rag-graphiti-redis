"""Module for PowerPoint files loader."""
from typing import List

try:
    from langchain_core.documents import Document
except ImportError:  # pragma: no cover
    from langchain.schema import Document  # type: ignore

from langchain_community.document_loaders import (
    UnstructuredPowerPointLoader as _Loader,
)


class PowerPointLoader:
    """PowerPoint document loader."""

    def __init__(self, path: str):
        self.loader = _Loader(path)

    def load(self) -> List[Document]:
        """
        Load PowerPoint documents.

        Returns:
            List[Document]: Loaded documents.
        """
        return self.loader.load()
