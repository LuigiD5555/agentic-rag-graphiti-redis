"""Maximal Marginal Relevance (MMR) for result diversification.

Implements Fase 6 del Plan Maestro:
- Anti-eco: avoid redundant/similar results
- Balance relevance with diversity
- Configurable lambda parameter
"""
import logging
from typing import List, Dict, Any, Optional
import numpy as np

logger = logging.getLogger(__name__)


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    """Calculate cosine similarity between two vectors.

    Args:
        vec1: First vector
        vec2: Second vector

    Returns:
        Cosine similarity (-1 to 1)
    """
    v1 = np.array(vec1)
    v2 = np.array(vec2)

    dot_product = np.dot(v1, v2)
    norm_v1 = np.linalg.norm(v1)
    norm_v2 = np.linalg.norm(v2)

    if norm_v1 == 0 or norm_v2 == 0:
        return 0.0

    return float(dot_product / (norm_v1 * norm_v2))


def mmr_rerank(
    documents: List[Dict[str, Any]],
    query_vector: Optional[List[float]] = None,
    lambda_param: float = 0.5,
    top_k: Optional[int] = None,
    score_key: str = "score",
    vector_key: str = "vector",
) -> List[Dict[str, Any]]:
    """Rerank documents using Maximal Marginal Relevance.

    MMR formula:
    MMR = λ * Relevance(query, doc) - (1-λ) * max(Similarity(doc, selected_docs))

    Args:
        documents: List of documents with scores and vectors
        query_vector: Query embedding (if None, uses score for relevance)
        lambda_param: Balance between relevance (1.0) and diversity (0.0)
                     Default: 0.5 (balanced)
        top_k: Number of documents to select (if None, returns all reranked)
        score_key: Key for relevance score in document dict
        vector_key: Key for document vector in document dict

    Returns:
        Reranked document list
    """
    if not documents:
        return []

    # If no vectors available, return original ranking
    if vector_key not in documents[0]:
        logger.warning(f"Documents missing '{vector_key}', returning original ranking")
        return documents[:top_k] if top_k else documents

    # Initialize
    selected: List[Dict[str, Any]] = []
    remaining = documents.copy()
    k = top_k or len(documents)

    # Precompute query relevance if query_vector provided
    if query_vector:
        for doc in remaining:
            doc_vector = doc.get(vector_key)
            if doc_vector:
                doc["_query_similarity"] = cosine_similarity(query_vector, doc_vector)
            else:
                doc["_query_similarity"] = doc.get(score_key, 0.0)
    else:
        # Use existing score as relevance
        for doc in remaining:
            doc["_query_similarity"] = doc.get(score_key, 0.0)

    # MMR selection loop
    while len(selected) < k and remaining:
        # For each remaining document, calculate MMR score
        mmr_scores = []

        for doc in remaining:
            relevance = doc["_query_similarity"]

            if not selected:
                # First document: only relevance matters
                mmr = relevance
            else:
                # Calculate max similarity to already selected documents
                doc_vector = doc.get(vector_key, [])
                max_similarity = 0.0

                for sel_doc in selected:
                    sel_vector = sel_doc.get(vector_key, [])
                    if doc_vector and sel_vector:
                        sim = cosine_similarity(doc_vector, sel_vector)
                        max_similarity = max(max_similarity, sim)

                # MMR formula
                mmr = lambda_param * relevance - (1 - lambda_param) * max_similarity

            mmr_scores.append((mmr, doc))

        # Select document with highest MMR
        if not mmr_scores:
            break

        mmr_scores.sort(key=lambda x: x[0], reverse=True)
        _, best_doc = mmr_scores[0]

        # Move to selected
        selected.append(best_doc)
        remaining.remove(best_doc)

    # Clean up temporary fields
    for doc in selected:
        doc.pop("_query_similarity", None)

    logger.debug(
        f"MMR reranking: {len(documents)} docs → {len(selected)} selected (λ={lambda_param})"
    )

    return selected


def mmr_filter_duplicates(
    documents: List[Dict[str, Any]],
    threshold: float = 0.85,
    vector_key: str = "vector",
) -> List[Dict[str, Any]]:
    """Filter near-duplicate documents using cosine similarity.

    Args:
        documents: List of documents with vectors
        threshold: Similarity threshold above which docs are considered duplicates
        vector_key: Key for document vector

    Returns:
        Filtered document list (duplicates removed)
    """
    if not documents:
        return []

    # Check if vectors available
    if vector_key not in documents[0]:
        logger.warning(f"Documents missing '{vector_key}', cannot filter duplicates")
        return documents

    filtered = []

    for doc in documents:
        doc_vector = doc.get(vector_key, [])
        if not doc_vector:
            filtered.append(doc)
            continue

        # Check similarity with already filtered docs
        is_duplicate = False
        for existing_doc in filtered:
            existing_vector = existing_doc.get(vector_key, [])
            if existing_vector:
                similarity = cosine_similarity(doc_vector, existing_vector)
                if similarity >= threshold:
                    is_duplicate = True
                    logger.debug(
                        f"Duplicate found: similarity={similarity:.2f} >= {threshold}"
                    )
                    break

        if not is_duplicate:
            filtered.append(doc)

    logger.info(
        f"Duplicate filtering: {len(documents)} docs → {len(filtered)} unique "
        f"({len(documents) - len(filtered)} duplicates removed)"
    )

    return filtered


class MMRReranker:
    """MMR-based reranker for result diversification."""

    def __init__(
        self,
        lambda_param: float = 0.5,
        duplicate_threshold: float = 0.85,
    ):
        """Initialize MMR reranker.

        Args:
            lambda_param: Balance between relevance and diversity (0.0-1.0)
            duplicate_threshold: Cosine similarity threshold for duplicate detection
        """
        self.lambda_param = lambda_param
        self.duplicate_threshold = duplicate_threshold

    def rerank(
        self,
        documents: List[Dict[str, Any]],
        query_vector: Optional[List[float]] = None,
        top_k: Optional[int] = None,
        remove_duplicates: bool = True,
    ) -> List[Dict[str, Any]]:
        """Rerank documents using MMR.

        Args:
            documents: List of documents to rerank
            query_vector: Query embedding
            top_k: Number of results to return
            remove_duplicates: Apply duplicate filtering first

        Returns:
            Reranked document list
        """
        if not documents:
            return []

        # Optional: filter duplicates first
        if remove_duplicates:
            documents = mmr_filter_duplicates(
                documents,
                threshold=self.duplicate_threshold,
            )

        # Apply MMR reranking
        reranked = mmr_rerank(
            documents,
            query_vector=query_vector,
            lambda_param=self.lambda_param,
            top_k=top_k,
        )

        return reranked


def create_mmr_reranker(
    lambda_param: float = 0.5,
    duplicate_threshold: float = 0.85,
) -> MMRReranker:
    """Factory function to create MMR reranker.

    Args:
        lambda_param: Balance between relevance (1.0) and diversity (0.0)
        duplicate_threshold: Similarity threshold for duplicate detection

    Returns:
        MMRReranker instance
    """
    return MMRReranker(lambda_param, duplicate_threshold)
