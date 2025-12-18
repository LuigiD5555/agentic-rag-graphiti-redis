from typing import List, Protocol

from langchain_core.documents import Document


class TextSplitter(Protocol):
    """Protocol for splitters that expose split_documents."""

    def split_documents(self, documents: List[Document]) -> List[Document]:
        ...

