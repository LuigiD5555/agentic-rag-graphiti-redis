"""
Pipeline — orchestrates the five layers in order for each query.

Flow:
  1. Perception Layer  (parallel encoders — F1 regex or F2 HF)
  2. Router            (reads perception, activates branches)
  3. Knowledge Layer   (Weaviate + Neo4j retrieval)
  4. Specialist Layer  (seq2seq — only active branches)
  5. Reasoning Layer   (integration + confidence scoring)
  6. Generator         (SLM verbalizer or LLM API escalation)

Factory method `build()` wires real implementations.
Constructor accepts callables for each layer for testing/customization.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from swarm_rag.schemas.blackboard_schema import BlackboardState
from swarm_rag.perception.perception_layer import run_perception
from swarm_rag.core.router import route
from swarm_rag.reasoning.integration_layer import run_integration

logger = logging.getLogger(__name__)


class SwarmPipeline:
    """
    End-to-end pipeline for a single query.

    Args:
        knowledge_layer:  async callable (state) -> state  (Weaviate + Neo4j)
        specialist_layer: async callable (state) -> state  (seq2seq specialists)
        reasoning_layer:  async callable (state) -> state  (integration)
        generator:        async callable (state) -> state  (SLM verbalizer)
    """

    def __init__(
        self,
        knowledge_layer: Optional[Any] = None,
        specialist_layer: Optional[Any] = None,
        reasoning_layer: Optional[Any] = None,
        generator: Optional[Any] = None,
    ) -> None:
        self._knowledge = knowledge_layer or _passthrough
        self._specialist = specialist_layer or _passthrough
        self._reasoning = reasoning_layer or run_integration  # real F3 by default
        self._generator = generator or _stub_generator

    @classmethod
    def build(
        cls,
        chat_interface: Any,
        llm_api_client: Optional[Any] = None,
        weaviate_retriever: Optional[Any] = None,
        neo4j_repository: Optional[Any] = None,
        knowledge_layer: Optional[Any] = None,
        specialist_layer: Optional[Any] = None,
        top_k: int = 10,
    ) -> "SwarmPipeline":
        """
        Build a fully wired SwarmPipeline.

        Args:
            chat_interface:     ChatInterface from ProviderFactory(config).chat()
            llm_api_client:     Optional LLMApiClient for escalation (Claude/DeepSeek)
            weaviate_retriever: WeaviateRetriever instance for semantic search
            neo4j_repository:   Neo4jRepository instance for graph retrieval (optional)
            knowledge_layer:    Override the auto-built knowledge layer callable
            specialist_layer:   Override the specialist layer callable
            top_k:              Max retrieval hits per source
        """
        from swarm_rag.generator.slm_verbalizer import SLMVerbalizer
        from swarm_rag.specialists.specialist_layer import run_specialists
        from swarm_rag.knowledge.knowledge_layer import build_knowledge_layer

        verbalizer = SLMVerbalizer(chat_interface, llm_api_client)

        async def _generator(state: BlackboardState) -> BlackboardState:
            return await verbalizer.run(state)

        # Build knowledge layer from retrievers if not explicitly provided
        if knowledge_layer is None and weaviate_retriever is not None:
            knowledge_layer = build_knowledge_layer(weaviate_retriever, neo4j_repository, top_k)

        return cls(
            knowledge_layer=knowledge_layer,
            specialist_layer=specialist_layer or run_specialists,
            reasoning_layer=run_integration,
            generator=_generator,
        )

    async def run(self, query: str, session_id: Optional[str] = None) -> BlackboardState:
        """Execute the full pipeline and return the final BlackboardState."""
        state = BlackboardState.new_session(query, session_id)
        t_total = time.monotonic()

        # 1. Perception Layer
        state = await run_perception(query, state)

        # 2. Router (sync — fast rule evaluation)
        route(state)

        # 3. Knowledge Layer (retrieval)
        if state.perception.needs_retrieval or state.perception.complexity != "low":
            state = await _timed(self._knowledge, state, "knowledge")

        # 4. Specialist Layer (conditional on router)
        if _has_specialist_branches(state):
            state = await _timed(self._specialist, state, "specialists")

        # 5. Reasoning / Integration Layer
        state = await _timed(self._reasoning, state, "reasoning")

        # 6. Generator (SLM or LLM API)
        state = await _timed(self._generator, state, "generator")

        state.latency_ms["total"] = round((time.monotonic() - t_total) * 1000, 2)
        logger.info(
            "Pipeline complete in %.1fms — intent=%s confidence=%.2f escalate=%s",
            state.latency_ms["total"],
            state.perception.intent,
            state.reasoning.confidence_score,
            state.reasoning.escalate_to_llm,
        )
        return state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_specialist_branches(state: BlackboardState) -> bool:
    specialist_names = {
        "query_rewriter", "subquestion_generator", "math_specialist",
        "math_tool_agent", "code_specialist", "code_agent_mcp",
        "fact_extractor", "hypothesis_generator",
    }
    return bool(set(state.active_branches) & specialist_names)


async def _timed(fn, state: BlackboardState, label: str) -> BlackboardState:
    t0 = time.monotonic()
    state = await fn(state)
    elapsed = round((time.monotonic() - t0) * 1000, 2)
    state.latency_ms[label] = elapsed
    state.execution_trace.append({"layer": label, "latency_ms": elapsed})
    return state


async def _passthrough(state: BlackboardState) -> BlackboardState:
    return state


async def _stub_reasoning(state: BlackboardState) -> BlackboardState:
    """F1 stub: build structured_answer from raw retrieval hits."""
    hits = state.retrieval.weaviate_hits + state.retrieval.neo4j_hits
    if hits:
        facts = "\n".join(
            f"- [{h.get('source', '?')}] {h.get('text', '')[:200]}"
            for h in hits[:8]
        )
        state.reasoning.structured_answer = (
            f"HECHOS RECUPERADOS:\n{facts}\n\n"
            f"CONSULTA ORIGINAL: {state.user_query}"
        )
        state.reasoning.confidence_score = min(0.5 + len(hits) * 0.05, 0.85)
    else:
        state.reasoning.structured_answer = (
            f"No se encontró información suficiente para: {state.user_query}"
        )
        state.reasoning.confidence_score = 0.1
        state.reasoning.escalate_to_llm = True
    return state


async def _stub_generator(state: BlackboardState) -> BlackboardState:
    """F1 stub: sets final_response = structured_answer (no LLM call yet)."""
    state.final_response = state.reasoning.structured_answer or ""
    return state
