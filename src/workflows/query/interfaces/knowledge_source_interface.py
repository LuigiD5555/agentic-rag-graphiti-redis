from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class QuerySourceInterface(ABC):
    """
    Consultable knowledge/context source used at query time by the RAG workflow.

    This interface is distinct from internal storage backends such as vector,
    graph, cache, SQL, or control-plane persistence. It models external or
    pluggable sources that can provide context during question answering.
    """

    @abstractmethod
    def name(self) -> str:
        """Unique source name."""
        raise NotImplementedError

    @abstractmethod
    def ensure_ready(self, source_name: str, vector_size: int) -> None:
        """Prepare the source for query-time use with the expected embedding size."""
        raise NotImplementedError

    @abstractmethod
    def ingest_context(
        self,
        source_name: str,
        vector: List[float],
        payload: Dict[str, Any],
        doc_id: Optional[str] = None,
    ) -> str:
        """Register or refresh consultable context and return the final item id."""
        raise NotImplementedError

    @abstractmethod
    def retrieve_context(
        self,
        source_name: str,
        vector: List[float],
        top_k: int = 5,
    ) -> List[Dict[str, Any]]:
        """Return the most relevant context items for the query vector."""
        raise NotImplementedError

    def close(self) -> None:
        """Optional cleanup for networked or stateful sources."""
        return
