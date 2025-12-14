from typing import Protocol, List

from langchain_core.documents import Document


class DocumentLoader(Protocol):
    def load(self) -> List[Document]:
        ...
