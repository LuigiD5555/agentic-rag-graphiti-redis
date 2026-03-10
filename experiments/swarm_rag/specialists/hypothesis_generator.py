"""
Hypothesis Generator — generates candidate answers before final synthesis.

Model: google/flan-t5-base (~990MB, seq2seq)
Input:  state.specialists.ranked_evidence + state.perception.intent + state.user_query
Output: state.specialists.hypotheses[] (list of candidate answer strings)

Each hypothesis is a plausible answer to the query derived from the evidence.
The Reasoning Layer then uses cosine similarity to score them against the
final evidence and picks the most consistent ones.

Hypotheses are ordered by the model's implicit confidence (position in output).
Fallback: derives one simple hypothesis directly from top evidence item.
"""
from __future__ import annotations

import logging
import time
from typing import Any, ClassVar, Optional

from experiments.swarm_rag.schemas.blackboard_schema import BlackboardState
from experiments.swarm_rag.specialists.base_specialist import BaseSpecialist

logger = logging.getLogger(__name__)

_MAX_NEW_TOKENS = 200
_MAX_HYPOTHESES = 3

_PROMPT_TEMPLATE = (
    "Based on the following evidence, generate {n} plausible answers to the question. "
    "Return one answer per line, ordered from most to least likely. Be specific.\n"
    "Question: {query}\n"
    "Evidence:\n{evidence}\n"
    "Candidate answers:"
)


def _format_evidence(ranked_evidence: list[dict], max_items: int = 4) -> str:
    lines = []
    for i, e in enumerate(ranked_evidence[:max_items], 1):
        fact = e.get("fact") or e.get("text", "")
        source = e.get("source", "")
        lines.append(f"{i}. [{source}] {fact[:200]}")
    return "\n".join(lines) if lines else "(no evidence available)"


class HypothesisGenerator(BaseSpecialist):
    name = "hypothesis_generator"
    model_id = "google/flan-t5-base"
    # Shared model with FactExtractor and SubquestionGenerator
    _model: ClassVar[Optional[Any]] = None
    _model_loaded: ClassVar[bool] = False

    @classmethod
    def _load_model(cls) -> Any:
        # Reuse already-loaded flan-t5-base if available
        from experiments.swarm_rag.specialists.fact_extractor import FactExtractor
        if FactExtractor._model is not None:
            cls._model = FactExtractor._model
            return cls._model
        from transformers import pipeline
        return pipeline(
            "text2text-generation",
            model=cls.model_id,
            max_new_tokens=_MAX_NEW_TOKENS,
        )

    async def run(self, state: BlackboardState) -> BlackboardState:
        evidence = state.specialists.ranked_evidence
        if not evidence:
            # Nothing to hypothesize from
            return state

        if not self._model_loaded:
            self.__class__.load()

        t0 = time.monotonic()

        if self._model is None:
            state.specialists.hypotheses = self._simple_hypothesis(state)
        else:
            evidence_str = _format_evidence(evidence)
            prompt = _PROMPT_TEMPLATE.format(
                n=_MAX_HYPOTHESES,
                query=state.specialists.rewritten_query or state.user_query,
                evidence=evidence_str,
            )
            try:
                raw = await self._run_in_executor(
                    lambda prompt_text: self._model(prompt_text)[0]["generated_text"], prompt
                )
                hypotheses = [
                    hypothesis_line.strip().lstrip("0123456789.-) ")
                    for hypothesis_line in raw.strip().split("\n")
                    if hypothesis_line.strip() and len(hypothesis_line.strip()) > 10
                ]
                state.specialists.hypotheses = hypotheses[:_MAX_HYPOTHESES] or self._simple_hypothesis(state)
            except Exception as exc:
                logger.warning("HypothesisGenerator failed: %s — using simple hypothesis", exc)
                state.specialists.hypotheses = self._simple_hypothesis(state)

        logger.info("HypothesisGenerator: %d hypotheses", len(state.specialists.hypotheses))
        self._record(state, round((time.monotonic() - t0) * 1000, 2))
        return state

    def _fallback(self, state: BlackboardState) -> BlackboardState:
        state.specialists.hypotheses = self._simple_hypothesis(state)
        return state

    @staticmethod
    def _simple_hypothesis(state: BlackboardState) -> list[str]:
        """Derive one hypothesis directly from the top ranked evidence."""
        evidence = state.specialists.ranked_evidence
        if not evidence:
            return []
        top = evidence[0]
        fact = top.get("fact") or top.get("text", "")
        if not fact:
            return []
        return [fact[:300]]
