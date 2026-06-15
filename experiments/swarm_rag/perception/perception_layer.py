"""
Perception Layer — runs all detectors in parallel via asyncio.gather.

Detector backend is selected at import time:
  - SWARM_HF_PERCEPTION=1 (env) or hf_perception: true (thresholds.yaml)
    → uses hf_detectors.py (MiniLM zero-shot, bert-NER, KeyBERT)
  - default → uses detectors.py (regex/heuristic, F1 stubs, no torch needed)

Both backends have identical async signatures — this file never changes.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from experiments.swarm_rag.schemas.blackboard_schema import BlackboardState, PerceptionOutput

logger = logging.getLogger(__name__)

# Select backend once at import time
_USE_HF = os.getenv("SWARM_HF_PERCEPTION", "0").strip() in ("1", "true", "yes")

if _USE_HF:
    logger.info("Perception Layer: using HuggingFace detectors (F2)")
    from experiments.swarm_rag.perception.hf_detectors import (
        detect_language, detect_math, detect_code,
        classify_intent, classify_domain, estimate_complexity,
        extract_entities, extract_keywords, classify_tone,
    )
else:
    from experiments.swarm_rag.perception.detectors import (
        detect_language, detect_math, detect_code,
        classify_intent, classify_domain, estimate_complexity,
        extract_entities, extract_keywords, classify_tone,
    )

async def run_perception(query: str, state: BlackboardState) -> BlackboardState:
    """
    Run all perception detectors in parallel and merge results into state.perception.

    Args:
        query: Raw user query string.
        state: BlackboardState to update (perception field written in-place).

    Returns:
        Updated BlackboardState.
    """
    t0 = time.monotonic()

    results: list[dict] = await asyncio.gather(
        classify_intent(query),
        classify_domain(query),
        detect_language(query),
        estimate_complexity(query),
        detect_math(query),
        detect_code(query),
        extract_entities(query),
        extract_keywords(query),
        classify_tone(query),
    )

    # Merge all partial dicts into a single flat dict
    merged: dict[str, Any] = {}
    for partial in results:
        merged.update(partial)

    # needs_retrieval: true unless it's a trivial low-complexity casual greeting
    merged.setdefault("needs_retrieval", True)
    if merged.get("complexity") == "low" and merged.get("intent") == "general":
        # Even then, retrieval is on by default — only disable explicitly if needed
        pass

    state.perception = PerceptionOutput(**merged)

    elapsed = round((time.monotonic() - t0) * 1000, 2)
    state.latency_ms["perception"] = elapsed
    state.execution_trace.append({"layer": "perception", "latency_ms": elapsed})

    logger.info(
        "Perception done in %.1fms — intent=%s domain=%s lang=%s "
        "complexity=%s math=%s code=%s",
        elapsed,
        state.perception.intent,
        state.perception.domain,
        state.perception.language,
        state.perception.complexity,
        state.perception.needs_math,
        state.perception.needs_code,
    )
    return state
