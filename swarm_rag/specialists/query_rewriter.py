"""
Query Rewriter — reformulates the user query for better retrieval.

Model: google/flan-t5-small (~300MB, seq2seq)
Input:  state.user_query + state.perception (intent, entities, domain)
Output: state.specialists.rewritten_query

If complexity == 'low', the original query is returned unchanged.
If model unavailable, original query is returned unchanged (safe fallback).
"""
from __future__ import annotations

import logging
import time
from typing import Any, ClassVar, Optional

from swarm_rag.schemas.blackboard_schema import BlackboardState
from swarm_rag.specialists.base_specialist import BaseSpecialist

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = (
    "Reformulate the following question to improve document retrieval. "
    "Keep the original intent. Remove ambiguity. Be specific.\n"
    "Intent: {intent}\n"
    "Domain: {domain}\n"
    "Entities: {entities}\n"
    "Original question: {query}\n"
    "Reformulated question:"
)

_MAX_NEW_TOKENS = 80
_MIN_CHANGE_RATIO = 0.1   # skip rewrite if output is < 10% different from input


class QueryRewriter(BaseSpecialist):
    name = "query_rewriter"
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
        # Skip rewrite for simple queries
        if state.perception.complexity == "low":
            state.specialists.rewritten_query = state.user_query
            return state

        if not self._model_loaded:
            self.__class__.load()

        if self._model is None:
            return self._fallback(state)

        t0 = time.monotonic()
        prompt = _PROMPT_TEMPLATE.format(
            intent=state.perception.intent,
            domain=state.perception.domain,
            entities=", ".join(state.perception.entities) or "none",
            query=state.user_query,
        )

        try:
            result = await self._run_in_executor(
                lambda p: self._model(p)[0]["generated_text"], prompt
            )
            rewritten = result.strip()
            # Only use rewrite if it meaningfully differs from original
            if rewritten and _is_meaningful(state.user_query, rewritten):
                state.specialists.rewritten_query = rewritten
                logger.info("QueryRewriter: '%s' → '%s'", state.user_query[:60], rewritten[:60])
            else:
                state.specialists.rewritten_query = state.user_query
        except Exception as exc:
            logger.warning("QueryRewriter failed: %s — using original query", exc)
            state.specialists.rewritten_query = state.user_query

        self._record(state, round((time.monotonic() - t0) * 1000, 2))
        return state

    def _fallback(self, state: BlackboardState) -> BlackboardState:
        state.specialists.rewritten_query = state.user_query
        return state


def _is_meaningful(original: str, rewritten: str) -> bool:
    """Return True if rewritten differs enough from original to be useful."""
    if not rewritten or rewritten.lower() == original.lower():
        return False
    orig_words = set(original.lower().split())
    new_words = set(rewritten.lower().split())
    # Jaccard distance > threshold means it's different enough
    if not orig_words | new_words:
        return False
    similarity = len(orig_words & new_words) / len(orig_words | new_words)
    return similarity < (1.0 - _MIN_CHANGE_RATIO)
