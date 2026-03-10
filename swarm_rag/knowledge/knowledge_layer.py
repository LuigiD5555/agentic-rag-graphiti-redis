"""
Knowledge Layer — parallel Weaviate + Neo4j retrieval followed by ContextCompressor.

Runs both retrievals in parallel (asyncio.gather), then applies the
ContextCompressor to deduplicate and score-filter before the Specialist Layer sees them.

Also runs VersionMonitor if 'retrieval_neo4j' is in active_branches.

Usage:
    knowledge_fn = build_knowledge_layer(weaviate_retriever, neo4j_repository)
    pipeline = SwarmPipeline.build(chat, knowledge_layer=knowledge_fn)
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from swarm_rag.schemas.blackboard_schema import BlackboardState
from swarm_rag.plugins.retrieval.plugin import RetrievalPlugin
from swarm_rag.plugins.graph_retrieval.plugin import GraphRetrievalPlugin
from swarm_rag.plugins.context_compressor.plugin import ContextCompressorPlugin
from swarm_rag.plugins.version_monitor.plugin import VersionMonitorPlugin

logger = logging.getLogger(__name__)

_compressor = ContextCompressorPlugin(min_score=0.3, max_hits=10)
_version_monitor = VersionMonitorPlugin()


def build_knowledge_layer(
    weaviate_retriever: Any,
    neo4j_repository: Optional[Any] = None,
    top_k: int = 10,
):
    """
    Factory: returns an async callable (state) -> state for the knowledge layer.

    Args:
        weaviate_retriever: WeaviateRetriever instance (from existing project)
        neo4j_repository:   Neo4jRepository instance (optional)
        top_k:              Max hits per retriever
    """
    retrieval_plugin = RetrievalPlugin(weaviate_retriever, top_k=top_k)
    graph_plugin = GraphRetrievalPlugin(neo4j_repository, limit=top_k * 3) if neo4j_repository else None

    async def run_knowledge(state: BlackboardState) -> BlackboardState:
        t0 = time.monotonic()
        active = set(state.active_branches)

        # Run Weaviate (always) and Neo4j (if active) in parallel
        tasks = [retrieval_plugin.run(state)]
        if graph_plugin and "retrieval_neo4j" in active:
            tasks.append(graph_plugin.run(state))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Merge results back — each plugin returns a modified copy
        for r in results:
            if isinstance(r, Exception):
                logger.error("Knowledge layer plugin error: %s", r)
                continue
            if r.retrieval.weaviate_hits:
                state.retrieval.weaviate_hits = r.retrieval.weaviate_hits
            if r.retrieval.neo4j_hits:
                state.retrieval.neo4j_hits = r.retrieval.neo4j_hits

        # Compress: deduplicate + score-filter
        state = await _compressor.run(state)

        # Version monitor (uses both hit lists)
        if state.retrieval.weaviate_hits or state.retrieval.neo4j_hits:
            state = await _version_monitor.run(state)

        elapsed = round((time.monotonic() - t0) * 1000, 2)
        state.latency_ms["knowledge"] = elapsed
        state.execution_trace.append({"layer": "knowledge", "latency_ms": elapsed})
        logger.info(
            "Knowledge layer done in %.1fms — weaviate=%d neo4j=%d conflicts=%d",
            elapsed,
            len(state.retrieval.weaviate_hits),
            len(state.retrieval.neo4j_hits),
            len(state.retrieval.version_conflicts),
        )
        return state

    return run_knowledge
