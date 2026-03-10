"""
Fact Extractor — extracts concrete facts from retrieved document chunks.

Model: google/flan-t5-base (~990MB, seq2seq)
Input:  state.retrieval.weaviate_hits (top chunks) + state.user_query
Output: state.specialists.extracted_facts (list of dicts)

Does NOT summarize — extracts specific, verifiable facts.
Each fact includes the source chunk_id for traceability.
"""
from __future__ import annotations

import logging
import time
from typing import Any, ClassVar, Optional

from swarm_rag.schemas.blackboard_schema import BlackboardState
from swarm_rag.specialists.base_specialist import BaseSpecialist

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = (
    "Extract all concrete facts from this text relevant to the question. "
    "Return one fact per line. Be specific. Do not paraphrase.\n"
    "Question: {query}\n"
    "Text: {text}\n"
    "Facts:"
)

_MAX_NEW_TOKENS = 200
_MAX_CHUNKS = 5          # process top-N chunks only (latency control)
_MIN_FACT_LENGTH = 10


class FactExtractor(BaseSpecialist):
    name = "fact_extractor"
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
        hits = (state.retrieval.weaviate_hits + state.retrieval.neo4j_hits)[:_MAX_CHUNKS]
        if not hits:
            return state

        if not self._model_loaded:
            self.__class__.load()

        if self._model is None:
            return self._fallback(state)

        t0 = time.monotonic()
        all_facts: list[dict] = []

        for hit in hits:
            text = hit.get("text", "").strip()
            if not text:
                continue
            prompt = _PROMPT_TEMPLATE.format(
                query=state.user_query,
                text=text[:600],   # truncate to avoid exceeding model context
            )
            try:
                raw = await self._run_in_executor(
                    lambda p: self._model(p)[0]["generated_text"], prompt
                )
                facts = [
                    f.strip() for f in raw.strip().split("\n")
                    if len(f.strip()) >= _MIN_FACT_LENGTH
                ]
                for fact in facts:
                    all_facts.append({
                        "fact": fact,
                        "source": hit.get("source", ""),
                        "chunk_id": hit.get("chunk_id", ""),
                        "score": hit.get("score", 0.0),
                    })
            except Exception as exc:
                logger.warning("FactExtractor failed on chunk %s: %s", hit.get("chunk_id"), exc)

        state.specialists.extracted_facts = all_facts
        logger.info("FactExtractor: %d facts from %d chunks", len(all_facts), len(hits))
        self._record(state, round((time.monotonic() - t0) * 1000, 2))
        return state

    def _fallback(self, state: BlackboardState) -> BlackboardState:
        # Degrade gracefully: convert raw hits to minimal fact dicts
        state.specialists.extracted_facts = [
            {"fact": h.get("text", "")[:200], "source": h.get("source", ""), "chunk_id": h.get("chunk_id", ""), "score": h.get("score", 0.0)}
            for h in state.retrieval.weaviate_hits[:_MAX_CHUNKS]
        ]
        return state
