"""
Retrieval plugin — wraps the existing WeaviateRetriever.

Reads user_query from the blackboard, runs hybrid search (BM25 + vector),
and writes results to state.retrieval.weaviate_hits.

top_k is read from manifest.json at construction time (default 10).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from experiments.swarm_rag.plugins.base_plugin import BasePlugin
from experiments.swarm_rag.schemas.blackboard_schema import BlackboardState

logger = logging.getLogger(__name__)


class RetrievalPlugin(BasePlugin):
    name = "retrieval"
    capabilities = ["semantic_search", "hybrid_search"]
    inputs = ["user_query"]
    outputs = ["retrieval.weaviate_hits"]
    dependencies = []

    def __init__(self, retriever: Any, top_k: int = 10) -> None:
        """
        Args:
            retriever: Instance of src.workflows.query.retrieval.WeaviateRetriever.
            top_k:     Max hits to write to the blackboard.
        """
        self._retriever = retriever
        self._top_k = top_k

    async def run(self, state: BlackboardState) -> BlackboardState:
        query = state.user_query
        loop = asyncio.get_event_loop()

        # WeaviateRetriever.retrieve is synchronous — run in thread pool
        results, meta = await loop.run_in_executor(
            None,
            lambda: self._retriever.retrieve(query, top_k=self._top_k),
        )

        if results:
            # Normalise to the blackboard hit schema
            state.retrieval.weaviate_hits = [
                {
                    "chunk_id": hit.get("uuid", ""),
                    "text": hit.get("text", ""),
                    "score": hit.get("score", 0.0),
                    "source": hit.get("source", ""),
                    "metadata": {
                        field_name: field_value
                        for field_name, field_value in hit.items()
                        if field_name not in ("uuid", "text", "score", "source")
                    },
                }
                for hit in results
            ]
            logger.info("Retrieval: %d hits (avg_score=%.3f)",
                        len(results), meta.get("avg_score") or 0.0)
        else:
            logger.warning("Retrieval: no hits for query='%.60s…'", query)

        return state
