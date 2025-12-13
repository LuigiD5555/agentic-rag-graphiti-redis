from typing import Protocol, List

try:
    from langchain_core.documents import Document
except ImportError:  # pragma: no cover
    from langchain.schema import Document  # type: ignore


class DocumentLoader(Protocol):
    def load(self) -> List[Document]:
        ...
