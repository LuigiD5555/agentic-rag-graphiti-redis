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

from experiments.swarm_rag.schemas.blackboard_schema import BlackboardState
from experiments.swarm_rag.plugins.retrieval.plugin import RetrievalPlugin
from experiments.swarm_rag.plugins.graph_retrieval.plugin import GraphRetrievalPlugin
from experiments.swarm_rag.plugins.context_compressor.plugin import ContextCompressorPlugin
from experiments.swarm_rag.plugins.version_monitor.plugin import VersionMonitorPlugin

logger = logging.getLogger(__name__)

_compressor = ContextCompressorPlugin(min_score=0.3, max_hits=10)
_version_monitor = VersionMonitorPlugin()


def build_knowledge_layer(
    weaviate_retriever: Any,
    neo4j_repository: Optional[Any] = None,
    memory_retriever: Optional[Any] = None,
    top_k: int = 10,
):
    """
    Factory: returns an async callable (state) -> state for the knowledge layer.

    Args:
        weaviate_retriever: WeaviateRetriever instance (from existing project)
        neo4j_repository:   Neo4jRepository instance (optional)
        top_k:              Max hits per retriever
    """
    from experiments.swarm_rag.knowledge.memory_retrieval import build_memory_retrieval
    from experiments.swarm_rag.knowledge.privacy_scrubber import run_privacy_scrubber

    retrieval_plugin = RetrievalPlugin(weaviate_retriever, top_k=top_k)
    graph_plugin = GraphRetrievalPlugin(neo4j_repository, limit=top_k * 3) if neo4j_repository else None
    memory_fn = build_memory_retrieval(memory_retriever) if memory_retriever else None

    async def run_knowledge(state: BlackboardState) -> BlackboardState:
        t0 = time.monotonic()
        active = set(state.active_branches)

        # Privacy scrubber FIRST — anonymize before any external retrieval
        if "privacy_scrubber" in active:
            state = await run_privacy_scrubber(state)

        # If RetrievalPlanner produced a plan, use its weaviate_queries for parallel retrieval
        plan = state.specialists.retrieved_plan
        if plan and plan.get("weaviate_queries"):
            # Run one retrieval per planned query (up to 3 for latency control)
            tasks = [
                retrieval_plugin.run(
                    state.model_copy(update={"user_query": q})
                )
                for q in plan["weaviate_queries"][:3]
            ]
        else:
            tasks = [retrieval_plugin.run(state)]

        if graph_plugin and "retrieval_neo4j" in active:
            tasks.append(graph_plugin.run(state))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Merge results back — accumulate hits across all parallel retrievals
        seen_chunks: set[str] = set()
        for retrieval_result in results:
            if isinstance(retrieval_result, Exception):
                logger.error("Knowledge layer plugin error: %s", retrieval_result)
                continue
            for hit in retrieval_result.retrieval.weaviate_hits:
                chunk_id = hit.get("chunk_id", "")
                if chunk_id not in seen_chunks:
                    seen_chunks.add(chunk_id)
                    state.retrieval.weaviate_hits.append(hit)
            if retrieval_result.retrieval.neo4j_hits:
                state.retrieval.neo4j_hits = retrieval_result.retrieval.neo4j_hits

        # Memory retrieval (past sessions)
        if memory_fn and "memory_retrieval" in active:
            state = await memory_fn(state)

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
