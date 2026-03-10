"""
Specialist Layer — runs the active specialists in the correct dependency order.

Dependency order (F2):
  1. QueryRewriter     (no deps — can run after perception)
  2. FactExtractor     (depends on retrieval hits being populated)
  3. EvidenceRanker    (depends on extracted_facts or raw hits)

Specialists not in active_branches are skipped.
All specialists degrade gracefully if their model is unavailable.

Pre-loads all registered models at startup via preload_all().
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from swarm_rag.schemas.blackboard_schema import BlackboardState
from swarm_rag.specialists.query_rewriter import QueryRewriter
from swarm_rag.specialists.fact_extractor import FactExtractor
from swarm_rag.specialists.evidence_ranker import EvidenceRanker

logger = logging.getLogger(__name__)

# Ordered list: each specialist only runs if its name is in active_branches
# Order matters — later specialists depend on earlier ones
_SPECIALIST_SEQUENCE = [
    QueryRewriter(),
    FactExtractor(),
    EvidenceRanker(),
]


def preload_all() -> None:
    """Load all specialist models at startup. Call once before serving requests."""
    for s in _SPECIALIST_SEQUENCE:
        logger.info("Preloading specialist: %s", s.name)
        s.__class__.load()


async def run_specialists(state: BlackboardState) -> BlackboardState:
    """
    Run each specialist in sequence if its name appears in active_branches.

    Args:
        state: BlackboardState after Knowledge Layer has run.

    Returns:
        Updated BlackboardState.
    """
    t0 = time.monotonic()
    active = set(state.active_branches)

    for specialist in _SPECIALIST_SEQUENCE:
        if specialist.name not in active:
            logger.debug("Skipping specialist '%s' (not in active branches)", specialist.name)
            continue
        try:
            state = await specialist.run(state)
        except Exception as exc:
            logger.error("Specialist '%s' raised: %s", specialist.name, exc, exc_info=True)
            # Continue — one failing specialist should not abort the pipeline

    elapsed = round((time.monotonic() - t0) * 1000, 2)
    state.latency_ms["specialists_total"] = elapsed
    state.execution_trace.append({"layer": "specialists", "latency_ms": elapsed})
    return state
