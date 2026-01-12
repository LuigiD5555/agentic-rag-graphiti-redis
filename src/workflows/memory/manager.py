"""Integration module for ChatMemory with conversation flow.

Connects all components:
- Snapshot creation triggers
- Persistence to Weaviate
- Cross-chat retrieval
- RRF fusion with KB results
- MMR anti-echo
"""
import logging
from typing import List, Dict, Any, Optional
import weaviate

from src.workflows.memory.core.state import ConversationState
from src.workflows.memory.snapshot import (
    create_snapshot,
    should_create_snapshot,
    ChatMemorySnapshot,
)
from src.workflows.memory.storage.chat_memory_persistence import (
    ChatMemoryPersistence,
    create_persistence,
)
from src.workflows.memory.retrieval.cross_chat import (
    CrossChatRetriever,
    create_cross_chat_retriever,
)
from src.workflows.memory.retrieval.rrf_fusion import combine_kb_and_memory
from src.workflows.memory.retrieval.mmr import create_mmr_reranker

logger = logging.getLogger(__name__)


class ChatMemoryManager:
    """Manages ChatMemory lifecycle: snapshot creation, persistence, retrieval."""

    def __init__(
        self,
        weaviate_client: weaviate.WeaviateClient,
        embedding_service: Optional[Any] = None,
        snapshot_ttl_days: int = 30,
        enable_cross_chat: bool = True,
        enable_rrf: bool = True,
        enable_mmr: bool = True,
        mmr_lambda: float = 0.5,
    ):
        """Initialize ChatMemory manager.

        Args:
            weaviate_client: Weaviate client instance
            embedding_service: Embedding service for snapshots
            snapshot_ttl_days: Default TTL for snapshots (days)
            enable_cross_chat: Enable cross-chat retrieval
            enable_rrf: Enable RRF fusion
            enable_mmr: Enable MMR anti-echo
            mmr_lambda: MMR diversity parameter (0.0=diversity, 1.0=relevance)
        """
        self.weaviate_client = weaviate_client
        self.embedding_service = embedding_service
        self.snapshot_ttl_days = snapshot_ttl_days
        self.enable_cross_chat = enable_cross_chat
        self.enable_rrf = enable_rrf
        self.enable_mmr = enable_mmr

        # Initialize components
        self.persistence = create_persistence(weaviate_client, embedding_service)
        self.cross_chat_retriever = create_cross_chat_retriever(self.persistence)
        self.mmr_reranker = create_mmr_reranker(lambda_param=mmr_lambda)

        logger.info(
            f"ChatMemoryManager initialized: "
            f"cross_chat={enable_cross_chat}, rrf={enable_rrf}, mmr={enable_mmr}"
        )

    def maybe_create_snapshot(
        self,
        state: ConversationState,
        user_id: str,
        thread_id: str,
        force: bool = False,
    ) -> Optional[ChatMemorySnapshot]:
        """Create snapshot if conditions are met.

        Args:
            state: Current conversation state
            user_id: User identifier
            thread_id: Thread identifier
            force: Force snapshot creation (bypass heuristics)

        Returns:
            Created snapshot or None
        """
        # Check if snapshot should be created
        if not force and not should_create_snapshot(state):
            logger.debug("Snapshot creation criteria not met")
            return None

        # Create snapshot
        snapshot = create_snapshot(
            state=state,
            user_id=user_id,
            thread_id=thread_id,
            ttl_days=self.snapshot_ttl_days,
            pinned=False,
        )

        # Persist to Weaviate
        success = self.persistence.save_snapshot(snapshot)

        if success:
            # Update state with snapshot timestamp
            from datetime import datetime
            state["last_snapshot_time"] = datetime.utcnow().strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"
            )
            logger.info(f"Snapshot created and saved for thread {thread_id[:8]}...")
            return snapshot
        else:
            logger.error("Failed to save snapshot")
            return None

    def retrieve_with_memory(
        self,
        query: str,
        user_id: str,
        kb_results: Optional[List[Dict[str, Any]]] = None,
        top_k: int = 10,
    ) -> Dict[str, Any]:
        """Retrieve results combining KB and ChatMemory.

        Args:
            query: User query
            user_id: User identifier
            kb_results: Results from Knowledge Base retrieval
            top_k: Number of final results

        Returns:
            Dictionary with combined results and metadata
        """
        results = {
            "kb_results": kb_results or [],
            "memory_results": [],
            "combined_results": [],
            "used_cross_chat": False,
            "used_rrf": False,
            "used_mmr": False,
        }

        # 1. Cross-chat retrieval (if enabled)
        if self.enable_cross_chat:
            try:
                memory_results = self.cross_chat_retriever.retrieve(
                    query=query,
                    user_id=user_id,
                    top_k=5,  # Fetch top 5 past conversations
                )
                results["memory_results"] = memory_results
                results["used_cross_chat"] = True

                logger.info(f"Cross-chat retrieval: {len(memory_results)} results")
            except Exception as e:
                logger.error(f"Cross-chat retrieval failed: {e}")

        # 2. RRF fusion (if enabled and we have results from both sources)
        if self.enable_rrf and kb_results and results["memory_results"]:
            try:
                combined = combine_kb_and_memory(
                    kb_results=kb_results,
                    memory_results=results["memory_results"],
                    rrf_k=60,
                    top_k=top_k * 2,  # Fetch more for MMR
                )
                results["combined_results"] = combined
                results["used_rrf"] = True

                logger.info(f"RRF fusion: {len(combined)} combined results")
            except Exception as e:
                logger.error(f"RRF fusion failed: {e}")
                results["combined_results"] = (kb_results or [])[:top_k]
        else:
            # No fusion: just use KB results or memory results
            results["combined_results"] = (kb_results or [])[:top_k]

        # 3. MMR anti-echo (if enabled)
        if self.enable_mmr and results["combined_results"]:
            try:
                # Generate query embedding for MMR
                query_vector = None
                if self.embedding_service:
                    try:
                        query_vector = self.embedding_service.generate(query)
                    except Exception as e:
                        logger.warning(f"Could not generate query embedding: {e}")

                # Apply MMR reranking
                reranked = self.mmr_reranker.rerank(
                    documents=results["combined_results"],
                    query_vector=query_vector,
                    top_k=top_k,
                    remove_duplicates=True,
                )
                results["combined_results"] = reranked
                results["used_mmr"] = True

                logger.info(f"MMR reranking: {len(reranked)} final results")
            except Exception as e:
                logger.error(f"MMR reranking failed: {e}")
                results["combined_results"] = results["combined_results"][:top_k]

        return results

    def format_memory_context(
        self,
        memory_results: List[Dict[str, Any]],
        max_length: int = 1000,
    ) -> str:
        """Format ChatMemory results for LLM context injection.

        Args:
            memory_results: Results from cross-chat retrieval
            max_length: Maximum character length

        Returns:
            Formatted context string
        """
        return self.cross_chat_retriever.format_for_context(
            memory_results,
            max_length=max_length,
        )

    def cleanup_expired(self, user_id: Optional[str] = None) -> int:
        """Cleanup expired snapshots.

        Args:
            user_id: Optional user filter

        Returns:
            Number of snapshots deleted
        """
        return self.persistence.cleanup_expired_snapshots(user_id)

    def get_user_snapshots(
        self,
        user_id: str,
        include_expired: bool = False,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get all snapshots for a user.

        Args:
            user_id: User identifier
            include_expired: Include expired snapshots
            limit: Maximum snapshots to return

        Returns:
            List of snapshots
        """
        return self.persistence.get_user_snapshots(
            user_id=user_id,
            include_expired=include_expired,
            limit=limit,
        )


def create_chat_memory_manager(
    weaviate_client: weaviate.WeaviateClient,
    embedding_service: Optional[Any] = None,
    snapshot_ttl_days: int = 30,
    enable_cross_chat: bool = True,
    enable_rrf: bool = True,
    enable_mmr: bool = True,
    mmr_lambda: float = 0.5,
) -> ChatMemoryManager:
    """Factory function to create ChatMemory manager.

    Args:
        weaviate_client: Weaviate client instance
        embedding_service: Embedding service for snapshots
        snapshot_ttl_days: Default TTL for snapshots (days)
        enable_cross_chat: Enable cross-chat retrieval
        enable_rrf: Enable RRF fusion
        enable_mmr: Enable MMR anti-echo
        mmr_lambda: MMR diversity parameter

    Returns:
        ChatMemoryManager instance
    """
    return ChatMemoryManager(
        weaviate_client=weaviate_client,
        embedding_service=embedding_service,
        snapshot_ttl_days=snapshot_ttl_days,
        enable_cross_chat=enable_cross_chat,
        enable_rrf=enable_rrf,
        enable_mmr=enable_mmr,
        mmr_lambda=mmr_lambda,
    )
