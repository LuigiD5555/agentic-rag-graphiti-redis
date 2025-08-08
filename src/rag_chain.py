"""Module that implements a hybrid RAG engine using vector and graph stores."""
from typing import Protocol, List, Any
from src import logger


# Protocol definitions

class EmbeddingServiceProtocol(Protocol):
    """Protocol for embedding services."""
    def generate(self, text: str) -> List[float]:
        ...


class VectorStoreProtocol(Protocol):
    """Protocol for vector store services."""
    def search(self, vector: List[float], top_k: int = 5) -> List[Any]:
        ...


class GraphStoreProtocol(Protocol):
    """Protocol for graph store services."""
    def search(self, query: str) -> List[str]:
        ...


class CacheServiceProtocol(Protocol):
    """Protocol for cache services."""
    def get(self, key: str) -> str | None:
        ...

    def set(self, key: str, value: str) -> None:
        ...


class LLMServiceProtocol(Protocol):
    """Protocol for LLM services."""
    def complete(self, prompt: str) -> str:
        ...


# RAG Engine

class RAGEngine:
    """
    Hybrid RAG engine combining vector search (Qdrant) and graph search (Neo4j),
    with optional caching for improved performance.
    """

    def __init__(
        self,
        embedding: EmbeddingServiceProtocol,
        vector_store: VectorStoreProtocol,
        graph_store: GraphStoreProtocol,
        cache: CacheServiceProtocol,
        llm: LLMServiceProtocol,
        mark_cache: bool = True
    ) -> None:
        self.embedding = embedding
        self.vector = vector_store
        self.graph = graph_store
        self.cache = cache
        self.llm = llm
        self.mark_cache = mark_cache

    # Internal helpers

    def _retrieve_vector_context(self, query: str, top_k: int = 5) -> str:
        """Retrieve context from vector store (Qdrant)."""
        logger.info("Retrieving vector context for query: %s", query)
        vector = self.embedding.generate(query)
        results = self.vector.search(vector, top_k=top_k) or []

        context_parts = []
        for hit in results:
            # Handle both dicts (tests) and objects with .payload (production)
            if isinstance(hit, dict):
                payload = hit.get("payload", {})
            else:
                payload = getattr(hit, "payload", {})
            context_parts.append(payload.get("content", ""))

        return "\n".join(context_parts)

    def _retrieve_graph_context(self, query: str) -> str:
        """Retrieve context from graph store (Neo4j)."""
        logger.info("Retrieving graph context for query: %s", query)
        results = self.graph.search(query)
        return "\n".join(results)

    def _build_prompt(self, query: str, vector_context: str, graph_context: str) -> str:
        """Construct the final prompt for the LLM using both contexts."""
        context = f"Vector DB:\n{vector_context}\n\nGraph:\n{graph_context}"
        return f"Context:\n{context}\n\nQuestion: {query}\nAnswer in detail:"

    # Public method

    def answer(self, query: str) -> str:
        """
        Generate an answer by combining vector + graph context with caching support.
        """
        # Check cache
        cached = self.cache.get(query)
        if cached:
            logger.info("Cache hit for query: %s", query)
            return f"[CACHE] {cached}" if self.mark_cache else cached

        # Retrieve contexts
        vector_context = self._retrieve_vector_context(query)
        graph_context = self._retrieve_graph_context(query)

        # Build prompt and get LLM completion
        prompt = self._build_prompt(query, vector_context, graph_context)
        response = self.llm.complete(prompt)

        # Cache response
        self.cache.set(query, response)
        logger.info("Cached response for query: %s", query)

        return response
