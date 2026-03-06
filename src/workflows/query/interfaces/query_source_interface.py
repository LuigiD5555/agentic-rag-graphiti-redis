from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class QuerySourceInterface(ABC):
    """
    Pluggable knowledge source consulted at query time by the RAG workflow.

    Each implementation wraps one external store (e.g. Weaviate, Neo4j,
    MongoDB, pgvector) and exposes a uniform retrieval contract.  This
    interface is query-time only — ingestion into each store is handled
    by the ingestion pipeline independently.

    Routing & gating
    ----------------
    The orchestrator skips any source whose ``enabled`` property returns
    False, so individual sources can be toggled without restarting.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique, stable identifier for this source (e.g. ``"weaviate"``)."""
        raise NotImplementedError

    @property
    def enabled(self) -> bool:
        """Return False to exclude this source from query routing."""
        return True

    @abstractmethod
    def retrieve_context(
        self,
        query: str,
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Return the most relevant context items for *query*.

        Each item must contain at least ``{"text": str, "source": str, "score": float}``.
        The source is responsible for embedding the query if needed.
        """
        raise NotImplementedError

    def close(self) -> None:
        """Optional cleanup for networked or stateful sources."""
        return


class WritableQuerySourceInterface(QuerySourceInterface):
    """
    Pluggable knowledge source that the RAG pipeline can both read and write.

    Extends ``QuerySourceInterface`` for stores that the RAG ingestion
    pipeline also populates (e.g. MongoDB, pgvector).  Sources that are
    externally managed or derived (Weaviate, Neo4j) should implement only
    ``QuerySourceInterface``.
    """

    @abstractmethod
    def store_context(
        self,
        payload: Dict[str, Any],
        doc_id: Optional[str] = None,
    ) -> str:
        """Persist a document chunk and return the assigned item id."""
        raise NotImplementedError

    @abstractmethod
    def delete_context(self, doc_id: str) -> None:
        """Remove all chunks associated with *doc_id*."""
        raise NotImplementedError
