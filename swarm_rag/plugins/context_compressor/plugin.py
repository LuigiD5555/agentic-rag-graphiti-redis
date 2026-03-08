"""
Context Compressor plugin — deduplicates and score-filters retrieval hits.

Operates on all three hit lists (weaviate, neo4j, memory) before the
Evidence Merger sees them. No LLM call needed at this phase.

Steps:
1. Remove hits below min_score threshold
2. Deduplicate by chunk_id (keep highest score)
3. Trim each list to max_hits
"""
from __future__ import annotations

import logging
from typing import Any

from swarm_rag.plugins.base_plugin import BasePlugin
from swarm_rag.schemas.blackboard_schema import BlackboardState

logger = logging.getLogger(__name__)


def _dedup_and_filter(
    hits: list[dict],
    min_score: float,
    max_hits: int,
) -> list[dict]:
    """Remove low-score hits, deduplicate by chunk_id, trim to max_hits."""
    # Score filter
    filtered = [h for h in hits if h.get("score", 0.0) >= min_score]

    # Dedup by chunk_id — keep highest score per id
    seen: dict[str, dict] = {}
    for hit in filtered:
        cid = hit.get("chunk_id") or hit.get("text", "")[:80]
        if cid not in seen or hit.get("score", 0.0) > seen[cid].get("score", 0.0):
            seen[cid] = hit

    # Sort by score descending, then trim
    deduped = sorted(seen.values(), key=lambda h: h.get("score", 0.0), reverse=True)
    return deduped[:max_hits]


class ContextCompressorPlugin(BasePlugin):
    name = "context_compressor"
    capabilities = ["deduplication", "summarization"]
    inputs = ["retrieval"]
    outputs = ["retrieval"]
    dependencies = ["retrieval"]

    def __init__(self, min_score: float = 0.3, max_hits: int = 10) -> None:
        self._min_score = min_score
        self._max_hits = max_hits

    async def run(self, state: BlackboardState) -> BlackboardState:
        before_w = len(state.retrieval.weaviate_hits)
        before_n = len(state.retrieval.neo4j_hits)
        before_m = len(state.retrieval.memory_hits)

        state.retrieval.weaviate_hits = _dedup_and_filter(
            state.retrieval.weaviate_hits, self._min_score, self._max_hits
        )
        state.retrieval.neo4j_hits = _dedup_and_filter(
            state.retrieval.neo4j_hits, self._min_score, self._max_hits
        )
        state.retrieval.memory_hits = _dedup_and_filter(
            state.retrieval.memory_hits, self._min_score, self._max_hits
        )

        logger.info(
            "ContextCompressor: weaviate %d→%d, neo4j %d→%d, memory %d→%d",
            before_w, len(state.retrieval.weaviate_hits),
            before_n, len(state.retrieval.neo4j_hits),
            before_m, len(state.retrieval.memory_hits),
        )
        return state
