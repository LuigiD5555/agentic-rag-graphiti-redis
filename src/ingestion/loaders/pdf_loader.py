from typing import List

try:
    from langchain_core.documents import Document
except ImportError:  # pragma: no cover
    from langchain.schema import Document  # type: ignore

from langchain_community.document_loaders import PyPDFLoader as _Loader


class PDFLoader:
    """PDF document loader."""
    def __init__(self, path: str):
        self.loader = _Loader(path)

    def load(self) -> List[Document]:
        """
        Load PDF documents.

        Return: List[Document]
        """
        return self.loader.load()
