"""
Graph Retrieval plugin — wraps the existing Neo4jRepository.

Extracts keywords from the blackboard (code_context.symbols + intents +
raw query words), queries the graph via get_related_context(), and writes
results to state.retrieval.neo4j_hits.

Version conflict detection is delegated to the VersionMonitor plugin.
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from swarm_rag.plugins.base_plugin import BasePlugin
from swarm_rag.schemas.blackboard_schema import BlackboardState

logger = logging.getLogger(__name__)

# Simple stopwords to strip from keyword extraction
_STOPWORDS = {
    "el", "la", "los", "las", "un", "una", "de", "del", "en", "con",
    "por", "para", "que", "qué", "es", "son", "hay", "se", "me", "te",
    "entre", "sobre", "desde", "hasta", "como", "cual", "cuál", "esto",
    "the", "is", "are", "of", "in", "and", "or", "a", "an", "to",
}


def _extract_keywords(state: BlackboardState, max_kw: int = 8) -> list[str]:
    """Derive keywords from code symbols, intents, and query tokens."""
    kw: list[str] = []
    # Symbols from code context
    kw.extend(state.code_context.symbols[:4])
    # Bare words from query (>3 chars, not stopwords)
    tokens = re.findall(r"[a-záéíóúüñA-Z]{4,}", state.user_query)
    kw.extend(t.lower() for t in tokens if t.lower() not in _STOPWORDS)
    # Deduplicate preserving order
    seen: set[str] = set()
    result = []
    for k in kw:
        if k not in seen:
            seen.add(k)
            result.append(k)
    return result[:max_kw]


class GraphRetrievalPlugin(BasePlugin):
    name = "graph_retrieval"
    capabilities = ["graph_search", "entity_lookup", "version_detection"]
    inputs = ["user_query", "intents"]
    outputs = ["retrieval.neo4j_hits", "version_conflicts"]
    dependencies = []

    def __init__(self, neo4j_repository: Any, limit: int = 30) -> None:
        """
        Args:
            neo4j_repository: Instance of src.backends.storage.graph.neo4j_repository.Neo4jRepository.
            limit:            Max edges to fetch from Neo4j.
        """
        self._repo = neo4j_repository
        self._limit = limit

    async def run(self, state: BlackboardState) -> BlackboardState:
        keywords = _extract_keywords(state)
        if not keywords:
            logger.debug("GraphRetrieval: no keywords extracted — skipping")
            return state

        loop = asyncio.get_event_loop()
        edges = await loop.run_in_executor(
            None,
            lambda: self._repo.get_related_context(keywords, max_hops=1, limit=self._limit),
        )

        if not edges:
            logger.info("GraphRetrieval: no edges for keywords=%s", keywords)
            return state

        # Normalise edges to blackboard hit schema
        state.retrieval.neo4j_hits = [
            {
                "chunk_id": f"neo4j:{e.get('source','')}:{e.get('relation','')}:{e.get('target','')}",
                "text": f"{e.get('source','')} -[{e.get('relation','')}]-> {e.get('target','')}",
                "score": 1.0,  # graph hits don't have a relevance score
                "source": e.get("topic") or "graph",
                "metadata": e,
            }
            for e in edges
        ]
        logger.info("GraphRetrieval: %d hits for keywords=%s", len(edges), keywords)
        return state
