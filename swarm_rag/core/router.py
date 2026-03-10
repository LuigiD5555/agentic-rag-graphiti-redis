"""
Router v2 — reads state.perception to decide which branches to activate.

Replaces the keyword-only v1 router. Rules are loaded from
config/router_rules.yaml but the primary logic is based on the structured
PerceptionOutput written by the Perception Layer.

Returns list[str] of branch names written to state.active_branches.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

try:
    import yaml
    _YAML_OK = True
except ImportError:
    _YAML_OK = False

from swarm_rag.schemas.blackboard_schema import BlackboardState

logger = logging.getLogger(__name__)

_RULES_PATH = Path(__file__).parent.parent / "config" / "router_rules.yaml"

# Branches always active (evidence_merger runs inside integration_layer, not as a separate branch)
_ALWAYS_ON = ["retrieval_weaviate"]


def route(state: BlackboardState) -> list[str]:
    """
    Decide which branches to activate based on state.perception.

    Writes result to state.active_branches and returns it.
    """
    p = state.perception
    active: list[str] = list(_ALWAYS_ON)

    # --- Retrieval branch ---
    if p.needs_retrieval or p.complexity != "low":
        if "retrieval_neo4j" not in active:
            active.append("retrieval_neo4j")

    # --- Specialist branch (conditional on complexity) ---
    if p.complexity in ("medium", "high"):
        active.append("query_rewriter")

    if p.complexity == "high":
        active += ["subquestion_generator", "retrieval_planner"]

    # --- Math branch (F3) ---
    if p.needs_math:
        active.append("math_specialist")
        # math_tool_agent: stub only — activate when MCP is connected
        # active.append("math_tool_agent")

    # --- Code branch (F3) ---
    if p.needs_code:
        active.append("code_specialist")
        # code_agent_mcp: stub only — activate when MCP/Digit is connected
        # active.append("code_agent_mcp")

    # --- Fact extraction + hypothesis: medium/high complexity ---
    if p.complexity in ("medium", "high"):
        active += ["fact_extractor", "hypothesis_generator"]

    # --- Version conflicts (populated by knowledge layer) ---
    if state.retrieval.version_conflicts:
        active.append("conflict_resolver")

    # --- Memory retrieval (session history) ---
    if p.intent == "memory" or any(kw in state.user_query.lower()
                                    for kw in ("recuerdas", "anteriormente", "antes", "previo")):
        active.append("memory_retrieval")

    # --- Privacy scrubber ---
    if any(kw in state.user_query.lower()
           for kw in ("confidencial", "privado", "secreto", "pii", "gdpr", "datos personales")):
        active.append("privacy_scrubber")

    # --- Reasoning always at the end ---
    active += ["evidence_ranker", "integration_layer"]

    # Deduplicate preserving order
    seen: set[str] = set()
    active = [b for b in active if not (b in seen or seen.add(b))]  # type: ignore[func-returns-value]

    state.active_branches = active
    logger.info(
        "Router activated %d branches for intent=%s complexity=%s: %s",
        len(active), p.intent, p.complexity, active,
    )
    return active
