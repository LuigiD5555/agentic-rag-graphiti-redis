"""
Specialist Layer — runs the active specialists in the correct dependency order.

Dependency order (F2 + F3):
  1. QueryRewriter          (no deps)
  2. SubquestionGenerator   (no deps, only high-complexity)
  3. MathSpecialist         (no deps, only when needs_math)
  4. CodeSpecialist         (no deps, only when needs_code)
  5. FactExtractor          (depends on retrieval hits)
  6. RetrievalPlanner       (depends on subquestions)
  7. EvidenceRanker         (depends on extracted_facts)
  8. HypothesisGenerator    (depends on ranked_evidence)

Specialists not in active_branches are skipped.
All specialists degrade gracefully if their model is unavailable.
Pre-loads all registered models at startup via preload_all().
"""
from __future__ import annotations

import logging
import time

from experiments.swarm_rag.schemas.blackboard_schema import BlackboardState
from experiments.swarm_rag.specialists.query_rewriter import QueryRewriter
from experiments.swarm_rag.specialists.subquestion_generator import SubquestionGenerator
from experiments.swarm_rag.specialists.math_specialist import MathSpecialist
from experiments.swarm_rag.specialists.code_specialist import CodeSpecialist
from experiments.swarm_rag.specialists.fact_extractor import FactExtractor
from experiments.swarm_rag.specialists.retrieval_planner import RetrievalPlanner
from experiments.swarm_rag.specialists.evidence_ranker import EvidenceRanker
from experiments.swarm_rag.specialists.hypothesis_generator import HypothesisGenerator

logger = logging.getLogger(__name__)

# Ordered: later specialists depend on earlier ones
_SPECIALIST_SEQUENCE = [
    QueryRewriter(),
    SubquestionGenerator(),
    MathSpecialist(),
    CodeSpecialist(),
    FactExtractor(),
    RetrievalPlanner(),
    EvidenceRanker(),
    HypothesisGenerator(),
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
