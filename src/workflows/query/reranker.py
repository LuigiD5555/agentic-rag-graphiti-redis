"""Bounded reranker for query-time result reordering.

Implements Step 7 from the unified plan:
- Rerank gating signals (only for RAG queries, not pure chat)
- Bounded rerank modes (mmr, cross_encoder, mmr_then_cross_encoder)
- Configurable candidate limits for latency bounding
- Integration with SQLite control plane for privacy-aware reranking
"""
import logging
import os
from typing import List, Dict, Any, Optional
from enum import Enum

from src.workflows.memory.retrieval.mmr import create_mmr_reranker
from src.workflows.query.sanitizer import get_sanitizer

logger = logging.getLogger(__name__)


# Direct settings access since AppConfig doesn't have these yet
def get_rerank_enabled() -> bool:
    """Get RERANK_ENABLED setting."""
    return os.getenv("RERANK_ENABLED", "false").strip().lower() == "true"


def get_rerank_max_candidates() -> int:
    """Get RERANK_MAX_CANDIDATES setting."""
    return int(os.getenv("RERANK_MAX_CANDIDATES", "20"))


def get_rerank_top_n() -> int:
    """Get RERANK_TOP_N setting."""
    return int(os.getenv("RERANK_TOP_N", "8"))


def get_rerank_mode() -> str:
    """Get RERANK_MODE setting."""
    return os.getenv("RERANK_MODE", "mmr")


class RerankMode(str, Enum):
    """Available reranking modes."""
    NONE = "none"
    MMR = "mmr"
    CROSS_ENCODER = "cross_encoder"
    MMR_THEN_CROSS_ENCODER = "mmr_then_cross_encoder"


class RerankGate:
    """Gate reranking based on query characteristics and system state."""
    
    def __init__(self):
        # Sanitizer requires session_id, so we'll get it lazily when needed
        self._sanitizer = None
    
    def should_rerank(
        self,
        query: str,
        retrieved_docs: List[Dict[str, Any]],
        intent: Optional[str] = None,
        is_pure_chat: bool = False,
        session_id: Optional[str] = None,
    ) -> bool:
        """Determine if reranking should be applied.
        
        According to the plan: "Ensure rerank never runs on pure chat."
        
        Args:
            query: User query
            retrieved_docs: Retrieved documents
            intent: Query intent (from classifier)
            is_pure_chat: Whether this is a pure chat query (no RAG context)
            session_id: Optional session ID for privacy context
            
        Returns:
            True if reranking should be applied
        """
        # Gate 1: Global rerank enabled setting
        if not get_rerank_enabled():
            logger.debug("Rerank disabled globally via settings")
            return False
        
        # Gate 2: Never rerank pure chat queries
        if is_pure_chat:
            logger.debug("Skipping rerank for pure chat query")
            return False
        
        # Gate 3: Need enough candidates
        if len(retrieved_docs) < 2:
            logger.debug("Skipping rerank: insufficient candidates (%d)", len(retrieved_docs))
            return False
        
        # Gate 4: Check privacy mode - if PII masking is ON, we might want to skip
        # cross-encoder (which needs full text) but still allow MMR (uses vectors)
        if session_id:
            try:
                sanitizer = get_sanitizer(session_id)
                # Check if PII masking is enabled for this session
                if not sanitizer.llm_pii_allowed:
                    logger.debug("PII masking enabled - will use vector-based reranking only")
            except Exception as e:
                logger.debug("Could not check privacy mode: %s", e)
        
        # Gate 5: Intent-based gating (optional)
        if intent and intent in ["SMALL_TALK", "PERSONAL_CHAT", "CONTROL"]:
            logger.debug("Skipping rerank for intent: %s", intent)
            return False
        
        return True


class BoundedReranker:
    """Bounded reranker with configurable modes and latency limits."""
    
    def __init__(
        self,
        mode: str = "mmr",
        max_candidates: Optional[int] = None,
        top_n: Optional[int] = None,
        mmr_lambda: float = 0.5,
    ):
        """Initialize bounded reranker.
        
        Args:
            mode: Reranking mode (none|mmr|cross_encoder|mmr_then_cross_encoder)
            max_candidates: Maximum candidates to consider for reranking
            top_n: Number of results to return after reranking
            mmr_lambda: Lambda parameter for MMR (0.0=diversity, 1.0=relevance)
        """
        self.mode = RerankMode(mode.lower())
        self.max_candidates = max_candidates or get_rerank_max_candidates()
        self.top_n = top_n or get_rerank_top_n()
        self.mmr_lambda = mmr_lambda
        
        # Initialize components based on mode
        self.mmr_reranker = None
        self.cross_encoder = None
        
        if self.mode in [RerankMode.MMR, RerankMode.MMR_THEN_CROSS_ENCODER]:
            self.mmr_reranker = create_mmr_reranker(lambda_param=mmr_lambda)
        
        if self.mode in [RerankMode.CROSS_ENCODER, RerankMode.MMR_THEN_CROSS_ENCODER]:
            # Lazy import cross-encoder if needed
            try:
                from sentence_transformers import CrossEncoder
                self.cross_encoder = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
                logger.info("Cross-encoder model loaded")
            except ImportError:
                logger.warning("sentence-transformers not installed, cross-encoder disabled")
                # Fall back to MMR-only if cross-encoder requested but not available
                if self.mode == RerankMode.CROSS_ENCODER:
                    self.mode = RerankMode.MMR
                    self.mmr_reranker = create_mmr_reranker(lambda_param=mmr_lambda)
                elif self.mode == RerankMode.MMR_THEN_CROSS_ENCODER:
                    self.mode = RerankMode.MMR
        
        self.gate = RerankGate()
        # Sanitizer requires session_id, so we'll get it lazily when needed
        self._sanitizer = None
        
        logger.info(
            "Initialized BoundedReranker: mode=%s, max_candidates=%d, top_n=%d, mmr_lambda=%.2f",
            self.mode.value, self.max_candidates, self.top_n, self.mmr_lambda
        )
    
    def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        query_vector: Optional[List[float]] = None,
        intent: Optional[str] = None,
        is_pure_chat: bool = False,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Apply bounded reranking to documents.
        
        Args:
            query: User query
            documents: Retrieved documents to rerank
            query_vector: Query embedding vector (for MMR)
            intent: Query intent classification
            is_pure_chat: Whether this is a pure chat query
            session_id: Optional session ID for privacy context
            
        Returns:
            Reranked documents (limited to top_n)
        """
        # Apply gating
        if not self.gate.should_rerank(query, documents, intent, is_pure_chat, session_id):
            return documents[:self.top_n]
        
        # Apply candidate bounding
        candidates = self._bound_candidates(documents)
        
        if not candidates:
            return []
        
        # Apply sanitization if needed (for cross-encoder that needs text)
        sanitized_query = query
        sanitized_candidates = candidates
        
        if session_id and self.mode in [RerankMode.CROSS_ENCODER, RerankMode.MMR_THEN_CROSS_ENCODER]:
            try:
                sanitizer = get_sanitizer(session_id)
                # Check if PII masking is enabled for this session
                if not sanitizer.llm_pii_allowed:
                    # Sanitize query and candidate texts for cross-encoder
                    sanitized_query, _, _ = sanitizer.sanitize_query(query)
                    sanitized_candidates = []
                    for doc in candidates:
                        sanitized_doc = doc.copy()
                        if "text" in sanitized_doc:
                            sanitized_text, _ = sanitizer.sanitize_context(sanitized_doc["text"])
                            sanitized_doc["text"] = sanitized_text
                        sanitized_candidates.append(sanitized_doc)
            except Exception as e:
                logger.debug("Could not sanitize for cross-encoder: %s", e)
        
        # Apply reranking based on mode
        reranked = self._apply_reranking(
            sanitized_query, sanitized_candidates, query_vector
        )
        
        # Return top_n results
        return reranked[:self.top_n]
    
    def _bound_candidates(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Limit candidates for latency bounding.
        
        Args:
            documents: Retrieved documents
            
        Returns:
            Bounded candidate list (max_candidates)
        """
        if len(documents) <= self.max_candidates:
            return documents
        
        # Take top candidates by score for reranking
        bounded = sorted(
            documents,
            key=lambda x: x.get("score", 0.0),
            reverse=True
        )[:self.max_candidates]
        
        logger.debug(
            "Bounded candidates: %d → %d for reranking",
            len(documents), len(bounded)
        )
        
        return bounded
    
    def _apply_reranking(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        query_vector: Optional[List[float]] = None,
    ) -> List[Dict[str, Any]]:
        """Apply reranking algorithm based on configured mode.
        
        Args:
            query: User query (sanitized if needed)
            candidates: Candidate documents (sanitized if needed)
            query_vector: Query embedding vector
            
        Returns:
            Reranked documents
        """
        if self.mode == RerankMode.NONE:
            return candidates
        
        elif self.mode == RerankMode.MMR:
            if not self.mmr_reranker:
                return candidates
            
            return self.mmr_reranker.rerank(
                documents=candidates,
                query_vector=query_vector,
                top_k=self.top_n,
                remove_duplicates=True,
            )
        
        elif self.mode == RerankMode.CROSS_ENCODER:
            if not self.cross_encoder:
                logger.warning("Cross-encoder not available, falling back to original")
                return candidates
            
            return self._apply_cross_encoder(query, candidates)
        
        elif self.mode == RerankMode.MMR_THEN_CROSS_ENCODER:
            # First apply MMR
            if not self.mmr_reranker:
                return candidates
            
            mmr_results = self.mmr_reranker.rerank(
                documents=candidates,
                query_vector=query_vector,
                top_k=min(self.top_n * 2, len(candidates)),  # Pass more to cross-encoder
                remove_duplicates=True,
            )
            
            # Then apply cross-encoder on MMR results
            if not self.cross_encoder:
                return mmr_results[:self.top_n]
            
            cross_results = self._apply_cross_encoder(query, mmr_results)
            return cross_results[:self.top_n]
        
        else:
            logger.warning("Unknown rerank mode: %s, returning original", self.mode)
            return candidates
    
    def _apply_cross_encoder(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Apply cross-encoder reranking.
        
        Args:
            query: User query
            candidates: Candidate documents
            
        Returns:
            Cross-encoder reranked documents
        """
        if not candidates:
            return []
        
        # Prepare query-document pairs
        pairs = []
        for doc in candidates:
            text = doc.get("text", "")
            if not text:
                # Fall back to other text fields
                text = doc.get("content", "") or doc.get("chunk_text", "")
            
            pairs.append((query, text))
        
        # Get cross-encoder scores
        try:
            scores = self.cross_encoder.predict(pairs)
            
            # Update documents with cross-encoder scores
            for i, doc in enumerate(candidates):
                doc["cross_encoder_score"] = float(scores[i])
                # Combine with original score if available
                if "score" in doc:
                    doc["combined_score"] = 0.7 * doc["cross_encoder_score"] + 0.3 * doc["score"]
                else:
                    doc["combined_score"] = doc["cross_encoder_score"]
            
            # Sort by combined score
            reranked = sorted(
                candidates,
                key=lambda x: x.get("combined_score", 0.0),
                reverse=True
            )
            
            logger.debug(
                "Cross-encoder reranking applied: %d candidates, scores %.3f-%.3f",
                len(candidates), min(scores), max(scores)
            )
            
            return reranked
            
        except Exception as e:
            logger.error("Cross-encoder failed: %s", e, exc_info=True)
            return candidates


def create_reranker(
    mode: Optional[str] = None,
    max_candidates: Optional[int] = None,
    top_n: Optional[int] = None,
    mmr_lambda: float = 0.5,
) -> BoundedReranker:
    """Factory function to create bounded reranker.
    
    Args:
        mode: Reranking mode (defaults to get_rerank_mode())
        max_candidates: Max candidates (defaults to get_rerank_max_candidates())
        top_n: Top N results (defaults to get_rerank_top_n())
        mmr_lambda: MMR lambda parameter
        
    Returns:
        BoundedReranker instance
    """
    mode = mode or get_rerank_mode()
    max_candidates = max_candidates or get_rerank_max_candidates()
    top_n = top_n or get_rerank_top_n()
    
    return BoundedReranker(
        mode=mode,
        max_candidates=max_candidates,
        top_n=top_n,
        mmr_lambda=mmr_lambda,
    )


# Global instance for convenience
_global_reranker: Optional[BoundedReranker] = None


def get_reranker() -> BoundedReranker:
    """Get global reranker instance (singleton pattern).
    
    Returns:
        Global BoundedReranker instance
    """
    global _global_reranker
    
    if _global_reranker is None:
        _global_reranker = create_reranker()
    
    return _global_reranker