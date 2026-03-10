"""
Retrieval Planner — decides what to search and where, based on the blackboard.

Model: google/flan-t5-small (~300MB, seq2seq)
Input:  state.perception (intent, entities, keywords) + state.specialists.subquestions
Output: state.specialists.retrieved_plan (dict with weaviate_queries, neo4j_queries, etc.)

When active, the planner replaces the router's default retrieval strategy
with a structured, targeted search plan. This is especially useful when
subquestions are available.

Fallback: builds a simple plan from perception.keywords directly.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, ClassVar, Optional

from experiments.swarm_rag.schemas.blackboard_schema import BlackboardState
from experiments.swarm_rag.specialists.base_specialist import BaseSpecialist

logger = logging.getLogger(__name__)

_MAX_NEW_TOKENS = 200

_PROMPT_TEMPLATE = (
    "Create a structured search plan for the following query.\n"
    "Intent: {intent}\n"
    "Domain: {domain}\n"
    "Keywords: {keywords}\n"
    "Sub-questions: {subquestions}\n"
    "Return a JSON object with keys: "
    "weaviate_queries (list of search strings), "
    "neo4j_focus (list of entity names to look up in graph), "
    "memory_query (single string for memory search, or null).\n"
    "JSON:"
)

_JSON_FALLBACK_RE = __import__("re").compile(r"\{.*?\}", __import__("re").DOTALL)


class RetrievalPlanner(BaseSpecialist):
    name = "retrieval_planner"
    model_id = "google/flan-t5-small"
    _model: ClassVar[Optional[Any]] = None
    _model_loaded: ClassVar[bool] = False

    @classmethod
    def _load_model(cls) -> Any:
        from transformers import pipeline
        return pipeline(
            "text2text-generation",
            model=cls.model_id,
            max_new_tokens=_MAX_NEW_TOKENS,
        )

    async def run(self, state: BlackboardState) -> BlackboardState:
        if not self._model_loaded:
            self.__class__.load()

        t0 = time.monotonic()

        if self._model is None:
            state.specialists.retrieved_plan = self._fallback_plan(state)
            self._record(state, round((time.monotonic() - t0) * 1000, 2))
            return state

        subquestions_str = "; ".join(state.specialists.subquestions) or "none"
        prompt = _PROMPT_TEMPLATE.format(
            intent=state.perception.intent,
            domain=state.perception.domain,
            keywords=", ".join(state.perception.keywords[:8]) or "none",
            subquestions=subquestions_str,
        )

        try:
            raw = await self._run_in_executor(
                lambda prompt_text: self._model(prompt_text)[0]["generated_text"], prompt
            )
            plan = self._parse_plan(raw, state)
        except Exception as exc:
            logger.warning("RetrievalPlanner failed: %s — using fallback plan", exc)
            plan = self._fallback_plan(state)

        state.specialists.retrieved_plan = plan
        logger.info(
            "RetrievalPlanner: %d weaviate queries, %d neo4j focus, memory=%s",
            len(plan.get("weaviate_queries", [])),
            len(plan.get("neo4j_focus", [])),
            bool(plan.get("memory_query")),
        )
        self._record(state, round((time.monotonic() - t0) * 1000, 2))
        return state

    def _fallback(self, state: BlackboardState) -> BlackboardState:
        state.specialists.retrieved_plan = self._fallback_plan(state)
        return state

    @staticmethod
    def _fallback_plan(state: BlackboardState) -> dict:
        """Build a simple plan from subquestions and keywords."""
        queries = list(state.specialists.subquestions) or [state.user_query]
        if state.specialists.rewritten_query:
            queries.insert(0, state.specialists.rewritten_query)
        return {
            "weaviate_queries": queries[:4],
            "neo4j_focus": state.perception.entities[:5],
            "memory_query": state.user_query if "memory" in state.active_branches else None,
            "parallel": True,
        }

    @staticmethod
    def _parse_plan(raw: str, state: BlackboardState) -> dict:
        """Try to parse JSON from model output; fallback to heuristic."""
        # Try direct JSON parse
        try:
            plan = json.loads(raw.strip())
            if isinstance(plan, dict):
                return plan
        except json.JSONDecodeError:
            pass

        # Try extracting JSON block from text
        match = _JSON_FALLBACK_RE.search(raw)
        if match:
            try:
                plan = json.loads(match.group(0))
                if isinstance(plan, dict):
                    return plan
            except json.JSONDecodeError:
                pass

        # Pure fallback
        return RetrievalPlanner._fallback_plan(state)
