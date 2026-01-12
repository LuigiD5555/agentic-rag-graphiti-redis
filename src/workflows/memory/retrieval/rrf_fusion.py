"""Reciprocal Rank Fusion (RRF) for combining search rankings.

Implements Fase 6 del Plan Maestro:
- Combine BM25 and vector search rankings
- Merge results from multiple sources (KB + ChatMemory)
- Configurable k parameter for RRF formula
"""
import logging
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)


def rrf_score(rank: int, k: int = 60) -> float:
    """Calculate RRF score for a given rank.

    Formula: 1 / (k + rank)

    Args:
        rank: Position in ranking (1-based)
        k: Constant parameter (default: 60, standard in literature)

    Returns:
        RRF score
    """
    return 1.0 / (k + rank)


def rrf_fusion(
    rankings: List[List[Dict[str, Any]]],
    k: int = 60,
    score_key: str = "score",
    id_key: str = "uuid",
) -> List[Dict[str, Any]]:
    """Fuse multiple rankings using Reciprocal Rank Fusion.

    Args:
        rankings: List of ranked result lists (each list is from one retriever)
        k: RRF constant parameter (default: 60)
        score_key: Key for original score in result dict
        id_key: Key for unique identifier in result dict

    Returns:
        Fused ranking sorted by RRF score
    """
    # Accumulate RRF scores for each document
    rrf_scores: Dict[str, float] = defaultdict(float)
    documents: Dict[str, Dict[str, Any]] = {}

    for ranking in rankings:
        for rank, doc in enumerate(ranking, start=1):
            doc_id = doc.get(id_key)
            if not doc_id:
                logger.warning(f"Document missing {id_key}, skipping")
                continue

            # Accumulate RRF score
            rrf_scores[doc_id] += rrf_score(rank, k)

            # Store document (keep first occurrence)
            if doc_id not in documents:
                documents[doc_id] = doc.copy()

    # Sort by RRF score (descending)
    sorted_docs = sorted(
        documents.items(),
        key=lambda x: rrf_scores[x[0]],
        reverse=True,
    )

    # Build final result list
    results = []
    for doc_id, doc in sorted_docs:
        doc["rrf_score"] = rrf_scores[doc_id]
        results.append(doc)

    logger.debug(
        f"RRF fusion: {len(rankings)} rankings → {len(results)} unique documents"
    )

    return results


class HybridRetriever:
    """Combines multiple retrievers using RRF fusion."""

    def __init__(
        self,
        retrievers: List[Tuple[str, Any]],  # [(name, retriever), ...]
        rrf_k: int = 60,
        top_k: int = 10,
    ):
        """Initialize hybrid retriever.

        Args:
            retrievers: List of (name, retriever) tuples
            rrf_k: RRF constant parameter
            top_k: Number of final results to return
        """
        self.retrievers = retrievers
        self.rrf_k = rrf_k
        self.top_k = top_k

    def retrieve(
        self,
        query: str,
        user_id: Optional[str] = None,
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve and fuse results from all retrievers.

        Args:
            query: Search query
            user_id: Optional user filter
            top_k: Override default top_k

        Returns:
            Fused ranking of results
        """
        k = top_k or self.top_k
        rankings = []

        # Gather results from each retriever
        for name, retriever in self.retrievers:
            try:
                # Call retriever (assume it has a .retrieve() method)
                if user_id and hasattr(retriever, 'retrieve'):
                    # Try with user_id parameter
                    try:
                        result = retriever.retrieve(query, user_id=user_id)
                    except TypeError:
                        # Fallback if retriever doesn't accept user_id
                        result = retriever.retrieve(query)
                else:
                    result = retriever.retrieve(query)

                # Handle both signatures: list or (results, metadata) tuple
                if isinstance(result, tuple):
                    results, metadata = result
                else:
                    results = result

                # Normalize None to empty list
                if results is None:
                    results = []

                rankings.append(results)
                logger.debug(f"Retriever '{name}' returned {len(results)} results")

            except Exception as e:
                logger.warning(f"Retriever '{name}' failed: {e}")
                rankings.append([])  # Empty ranking

        # Fuse rankings with RRF
        if not rankings or all(len(r) == 0 for r in rankings):
            logger.warning("All retrievers returned empty results")
            return []

        fused = rrf_fusion(rankings, k=self.rrf_k)

        # Return top-k
        results = fused[:k]

        logger.info(
            f"Hybrid retrieval: {len(results)} results from {len(self.retrievers)} sources"
        )

        return results


def create_hybrid_retriever(
    kb_retriever: Any,
    chat_memory_retriever: Any,
    rrf_k: int = 60,
    top_k: int = 10,
) -> HybridRetriever:
    """Factory function to create hybrid retriever for KB + ChatMemory.

    Args:
        kb_retriever: Knowledge Base retriever (WeaviateRetriever)
        chat_memory_retriever: ChatMemory retriever (CrossChatRetriever)
        rrf_k: RRF constant parameter
        top_k: Number of final results

    Returns:
        HybridRetriever instance
    """
    retrievers = [
        ("knowledge_base", kb_retriever),
        ("chat_memory", chat_memory_retriever),
    ]

    return HybridRetriever(retrievers, rrf_k, top_k)


def combine_kb_and_memory(
    kb_results: List[Dict[str, Any]],
    memory_results: List[Dict[str, Any]],
    rrf_k: int = 60,
    top_k: int = 10,
) -> List[Dict[str, Any]]:
    """Utility function to combine KB and ChatMemory results.

    Args:
        kb_results: Results from Knowledge Base retrieval
        memory_results: Results from ChatMemory retrieval
        rrf_k: RRF constant parameter
        top_k: Number of final results

    Returns:
        Fused ranking
    """
    # Ensure unique IDs for each source
    for i, doc in enumerate(kb_results):
        if "uuid" not in doc:
            doc["uuid"] = f"kb_{i}"
        doc["source_type"] = "knowledge_base"

    for i, doc in enumerate(memory_results):
        if "uuid" not in doc:
            doc["uuid"] = f"mem_{i}"
        doc["source_type"] = "chat_memory"

    # Fuse
    fused = rrf_fusion([kb_results, memory_results], k=rrf_k)

    return fused[:top_k]
