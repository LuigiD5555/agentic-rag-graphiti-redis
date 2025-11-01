"""Module that implements a hybrid RAG engine using vector and graph stores."""
from typing import Optional, Dict, Any, List
from src.interfaces.embedding_interface import EmbeddingInterface
from src.interfaces.vector_interface import VectorInterface, ScoredItem
from src.interfaces.graph_interface import GraphInterface
from src.cache.redis_cache import CacheService
from src.interfaces.chat_interface import ChatInterface
from src import logger


def _build_user_filter(user_id: Optional[str]) -> Dict[str, Any]:
    """
    Backend-agnostic filter description.
    The vector backend will translate this to its own query/filter format.
    Semantics:
      - visibility == 'public' OR
      - owner_id == user_id OR
      - allowed_user_ids contains user_id
    """
    if not user_id:
        return {"visibility": "public"}
    return {
        "user_id": user_id,     # for allowed_user_ids contains
        "owner_id": user_id,    # allow owner docs
        "visibility": "public", # always include public
    }


class RAGEngine:
    """
    Hybrid RAG engine combining vector search and graph search,
    with optional caching for improved performance.
    """

    def __init__(
        self,
        embedding: EmbeddingInterface,
        vector_store: VectorInterface,
        graph_store: GraphInterface,
        cache: CacheService,
        llm: ChatInterface,
        mark_cache: bool = True,
        default_top_k: int = 5,
        default_tenant: Optional[str] = None,
    ) -> None:
        self.embedding = embedding
        self.vector = vector_store
        self.graph = graph_store
        self.cache = cache
        self.llm = llm
        self.mark_cache = mark_cache
        self.default_top_k = default_top_k
        self.default_tenant = default_tenant

    def _retrieve_vector_context(
        self,
        query: str,
        top_k: Optional[int] = None,
        user_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> str:
        """Retrieve context from vector store (backend-agnostic)."""
        logger.info("Retrieving vector context for query: %s", query)
        vector = self.embedding.generate(query)
        filters = _build_user_filter(user_id)
        hits: List[ScoredItem] = self.vector.search(
            vector=vector,
            top_k=top_k or self.default_top_k,
            filters=filters,
            tenant_id=tenant_id or self.default_tenant,
        ) or []

        parts: List[str] = []
        for h in hits:
            payload = h.payload or {}
            parts.append(payload.get("content") or payload.get("structure_summary") or "")
        return "\n".join([p for p in parts if p])

    def _retrieve_graph_context(self, query: str) -> str:
        """Retrieve context from graph store (Neo4j)."""
        logger.info("Retrieving graph context for query: %s", query)
        results = self.graph.search(query)
        return "\n".join(results)

    def _build_prompt(self, query: str, vector_context: str, graph_context: str) -> str:
        """Construct the final prompt for the LLM using both contexts."""
        context = f"Vector DB:\n{vector_context}\n\nGraph:\n{graph_context}"
        return f"Context:\n{context}\n\nQuestion: {query}\nAnswer in detail:"

    def answer(self, query: str, user_id: Optional[str] = None, tenant_id: Optional[str] = None) -> str:
        """
        Generate an answer by combining vector + graph context with caching support.
        """
        cache_key = f"{tenant_id or ''}|{user_id or ''}|{query}"
        cached = self.cache.get(cache_key)
        if cached:
            logger.info("Cache hit for query: %s", query)
            return f"[CACHE] {cached}" if self.mark_cache else cached

        vector_context = self._retrieve_vector_context(query, user_id=user_id, tenant_id=tenant_id)
        graph_context = self._retrieve_graph_context(query)

        prompt = self._build_prompt(query, vector_context, graph_context)
        response = self.llm.complete(prompt)

        self.cache.set(cache_key, response)
        logger.info("Cached response for key: %s", cache_key)

        return response
