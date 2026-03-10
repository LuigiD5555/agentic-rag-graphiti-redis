"""
Subquestion Generator — decomposes complex queries into sub-questions.

Model: google/flan-t5-base (~990MB, seq2seq)
Input:  state.user_query + state.perception.complexity + state.perception.intent
Output: state.specialists.subquestions[]

Only runs when complexity == 'high'. Each sub-question is then used
by the Retrieval Planner to issue targeted searches in parallel.

Fallback (no model): splits the query heuristically on conjunctions.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, ClassVar, Optional

from swarm_rag.schemas.blackboard_schema import BlackboardState
from swarm_rag.specialists.base_specialist import BaseSpecialist

logger = logging.getLogger(__name__)

_MAX_NEW_TOKENS = 120
_MAX_SUBQUESTIONS = 5

_PROMPT_TEMPLATE = (
    "Divide the following complex question into {n} specific sub-questions "
    "that can each be answered independently. "
    "Return one sub-question per line. Be concise.\n"
    "Intent: {intent}\n"
    "Complex question: {query}\n"
    "Sub-questions:"
)

# Heuristic split patterns (fallback)
_SPLIT_PATTERNS = re.compile(
    r"\b(y además|además|también|asimismo|por otro lado|and also|furthermore|moreover"
    r"|compara|vs\.|versus|compare|¿|y ¿)\b",
    re.IGNORECASE,
)


class SubquestionGenerator(BaseSpecialist):
    name = "subquestion_generator"
    model_id = "google/flan-t5-base"
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
        # Only decompose high-complexity queries
        if state.perception.complexity != "high":
            return state

        if not self._model_loaded:
            self.__class__.load()

        t0 = time.monotonic()

        if self._model is None:
            state.specialists.subquestions = self._heuristic_split(state.user_query)
        else:
            prompt = _PROMPT_TEMPLATE.format(
                n=_MAX_SUBQUESTIONS,
                intent=state.perception.intent,
                query=state.user_query,
            )
            try:
                raw = await self._run_in_executor(
                    lambda prompt_text: self._model(prompt_text)[0]["generated_text"], prompt
                )
                subquestions = [
                    line.strip().lstrip("0123456789.-) ")
                    for line in raw.strip().split("\n")
                    if line.strip() and len(line.strip()) > 5
                ]
                state.specialists.subquestions = subquestions[:_MAX_SUBQUESTIONS]
                if not state.specialists.subquestions:
                    state.specialists.subquestions = self._heuristic_split(state.user_query)
            except Exception as exc:
                logger.warning("SubquestionGenerator failed: %s — using heuristic split", exc)
                state.specialists.subquestions = self._heuristic_split(state.user_query)

        logger.info("SubquestionGenerator: %d sub-questions", len(state.specialists.subquestions))
        self._record(state, round((time.monotonic() - t0) * 1000, 2))
        return state

    def _fallback(self, state: BlackboardState) -> BlackboardState:
        state.specialists.subquestions = self._heuristic_split(state.user_query)
        return state

    @staticmethod
    def _heuristic_split(query: str) -> list[str]:
        """Split on conjunctions/contrast markers as a fallback."""
        parts = _SPLIT_PATTERNS.split(query)
        subquestion_candidates = [part.strip() for part in parts if len(part.strip()) > 10]
        if len(subquestion_candidates) <= 1:
            return [query]  # can't split — return original as single sub-question
        return subquestion_candidates[:_MAX_SUBQUESTIONS]
