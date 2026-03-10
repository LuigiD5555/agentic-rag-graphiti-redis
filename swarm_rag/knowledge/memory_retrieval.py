"""
Memory Retrieval — searches past conversation sessions for relevant solutions.

Wraps the existing CrossChatRetriever from src/workflows/memory/retrieval/.
Writes results to state.retrieval.memory_hits in the standard hit schema.

Only runs when 'memory_retrieval' is in active_branches (router activates this
when query contains memory keywords: 'recuerdas', 'anteriormente', etc.)

If no memory system is available, gracefully returns without writing hits.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from swarm_rag.schemas.blackboard_schema import BlackboardState

logger = logging.getLogger(__name__)


def build_memory_retrieval(
    cross_chat_retriever: Any,
    user_id: str = "default",
    top_k: int = 3,
):
    """
    Factory: returns an async callable that retrieves memory hits.

    Args:
        cross_chat_retriever: CrossChatRetriever instance from existing project
        user_id:              User/session identifier for memory lookup
        top_k:                Max memory hits to retrieve
    """
    async def retrieve_memory(state: BlackboardState) -> BlackboardState:
        if "memory_retrieval" not in state.active_branches:
            return state

        # Use rewritten query if available, else original
        query = state.specialists.rewritten_query or state.user_query
        loop = asyncio.get_event_loop()

        try:
            raw = await loop.run_in_executor(
                None,
                lambda: cross_chat_retriever.retrieve(query, user_id=user_id, top_k=top_k),
            )
            if raw:
                state.retrieval.memory_hits = [
                    {
                        "chunk_id": f"memory:{i}",
                        "text": hit.get("summary") or hit.get("content") or str(hit),
                        "score": float(hit.get("relevance_score", 0.5)),
                        "source": f"session:{hit.get('session_id', 'unknown')}",
                        "metadata": hit,
                    }
                    for i, hit in enumerate(raw)
                ]
                logger.info("MemoryRetrieval: %d hits for query='%.60s'", len(raw), query)
        except Exception as exc:
            logger.warning("MemoryRetrieval failed: %s — no memory hits", exc)

        return state

    return retrieve_memory
