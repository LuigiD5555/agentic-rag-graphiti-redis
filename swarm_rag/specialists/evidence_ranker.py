"""
Evidence Ranker — scores and ranks evidence by relevance to the query.

Model: cross-encoder/ms-marco-MiniLM-L-6-v2 (~90MB, cross-encoder)
Input:  state.specialists.extracted_facts OR state.retrieval.weaviate_hits + state.user_query
Output: state.specialists.ranked_evidence (sorted by relevance score, filtered)

Uses sentence_transformers.CrossEncoder for passage-level relevance scoring.
Much more accurate than embedding similarity for ranking because it sees
both the query and the passage together.
"""
from __future__ import annotations

import logging
import time
from typing import Any, ClassVar, Optional

from swarm_rag.schemas.blackboard_schema import BlackboardState
from swarm_rag.specialists.base_specialist import BaseSpecialist

logger = logging.getLogger(__name__)

_MIN_SCORE = 0.3
_MAX_EVIDENCE = 10


class EvidenceRanker(BaseSpecialist):
    name = "evidence_ranker"
    model_id = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    _model: ClassVar[Optional[Any]] = None
    _model_loaded: ClassVar[bool] = False

    @classmethod
    def _load_model(cls) -> Any:
        from sentence_transformers import CrossEncoder
        return CrossEncoder(cls.model_id)

    async def run(self, state: BlackboardState) -> BlackboardState:
        # Use extracted_facts if available, else fall back to raw weaviate hits
        candidates = state.specialists.extracted_facts or [
            {"fact": h.get("text", ""), **h}
            for h in state.retrieval.weaviate_hits + state.retrieval.neo4j_hits
        ]

        if not candidates:
            return state

        if not self._model_loaded:
            self.__class__.load()

        if self._model is None:
            return self._fallback(state, candidates)

        t0 = time.monotonic()
        query = state.specialists.rewritten_query or state.user_query

        # Build (query, passage) pairs for cross-encoder
        texts = [c.get("fact") or c.get("text", "") for c in candidates]
        pairs = [[query, t] for t in texts]

        try:
            scores = await self._run_in_executor(
                lambda p: list(self._model.predict(p)), pairs
            )
            ranked = sorted(
                [{**c, "score": s} for s, c in zip(scores, candidates)],  # ranker score wins
                key=lambda x: x["score"],
                reverse=True,
            )
            # Filter below threshold and cap at max
            state.specialists.ranked_evidence = [
                r for r in ranked if r["score"] >= _MIN_SCORE
            ][:_MAX_EVIDENCE]

            logger.info(
                "EvidenceRanker: %d→%d evidence items (min_score=%.2f)",
                len(candidates), len(state.specialists.ranked_evidence), _MIN_SCORE,
            )
        except Exception as exc:
            logger.warning("EvidenceRanker failed: %s — using unranked", exc)
            return self._fallback(state, candidates)

        self._record(state, round((time.monotonic() - t0) * 1000, 2))
        return state

    def _fallback(self, state: BlackboardState, candidates: list[dict]) -> BlackboardState:
        # Sort by existing score field if present, else keep original order
        state.specialists.ranked_evidence = sorted(
            candidates, key=lambda x: x.get("score", 0.0), reverse=True
        )[:_MAX_EVIDENCE]
        return state
