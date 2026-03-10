"""
Integration / Reasoning Layer — fuses all specialist outputs into a
structured_answer and computes confidence_score + escalation decision.

Steps:
  1. Build structured_answer from ranked_evidence + specialist outputs
  2. Estimate confidence via ConfidenceEstimator
  3. Decide escalate_to_llm if confidence < threshold or conflicts > max

Reads threshold from config/thresholds.yaml.
Writes to state.reasoning (structured_answer, confidence_score, escalate_to_llm, key_points).
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

try:
    import yaml as _yaml
    _YAML_OK = True
except ImportError:
    _YAML_OK = False

from swarm_rag.schemas.blackboard_schema import BlackboardState
from swarm_rag.reasoning.confidence_estimator import estimate_confidence
from swarm_rag.reasoning.logic_checker import check_consistency
from swarm_rag.reasoning.conflict_resolver import resolve_conflicts

logger = logging.getLogger(__name__)

_THRESHOLDS_PATH = Path(__file__).parent.parent / "config" / "thresholds.yaml"
_SEP = "\n" + "─" * 60 + "\n"

# Defaults (overridden by thresholds.yaml)
_ESCALATION_THRESHOLD = 0.6
_MAX_CONFLICTS = 2


def _load_thresholds() -> tuple[float, int]:
    if not _YAML_OK or not _THRESHOLDS_PATH.exists():
        return _ESCALATION_THRESHOLD, _MAX_CONFLICTS
    try:
        data = _yaml.safe_load(_THRESHOLDS_PATH.read_text())
        r = data.get("reasoning", {})
        return (
            float(r.get("escalation_threshold", _ESCALATION_THRESHOLD)),
            int(r.get("max_unresolved_conflicts", _MAX_CONFLICTS)),
        )
    except Exception:
        return _ESCALATION_THRESHOLD, _MAX_CONFLICTS


def _build_structured_answer(state: BlackboardState) -> tuple[str, list[str]]:
    """Build the structured context string the SLM will verbalize."""
    sections: list[str] = []
    key_points: list[str] = []

    # 1. Ranked evidence (primary source of truth)
    evidence = state.specialists.ranked_evidence or (
        state.retrieval.weaviate_hits + state.retrieval.neo4j_hits
    )
    if evidence:
        lines = ["HECHOS CONFIRMADOS:"]
        for i, e in enumerate(evidence[:8], 1):
            fact = e.get("fact") or e.get("text", "")
            source = e.get("source", "?")
            score = e.get("score", 0.0)
            line = f"- [{source}] {fact[:250]}"
            lines.append(line)
            if i <= 3:
                key_points.append(fact[:120])
        sections.append("\n".join(lines))

    # 2. Math result
    if state.specialists.math_result is not None:
        sections.append(f"RESULTADO MATEMÁTICO:\n- {state.specialists.math_result}")
        key_points.append(f"Math result: {state.specialists.math_result}")

    # 3. Code analysis
    if state.specialists.code_analysis:
        ca = state.specialists.code_analysis
        parts = [f"Lenguaje: {ca.get('language', '?')}"]
        if ca.get("result"):
            parts.append(f"Resultado: {ca['result']}")
        if ca.get("issues"):
            parts.append("Problemas: " + "; ".join(ca["issues"]))
        sections.append("ANÁLISIS DE CÓDIGO:\n" + "\n".join(f"- {p}" for p in parts))

    # 4. Version conflicts
    conflicts = state.retrieval.version_conflicts
    if conflicts:
        lines = ["CONFLICTOS DE VERSIÓN DETECTADOS:"]
        for c in conflicts[:3]:
            lines.append(f"- {c.get('description', str(c))}")
        sections.append("\n".join(lines))

    # 5. Resolved conflicts (F4)
    if state.specialists.conflicts_found:
        lines = ["CONFLICTOS ANALIZADOS:"]
        for c in state.specialists.conflicts_found[:3]:
            res = c.get("resolution", "?")
            note = c.get("note", c.get("description", ""))
            lines.append(f"- [{res}] {note[:150]}")
        sections.append("\n".join(lines))

    # 6. Hypotheses (F3+)
    if state.specialists.hypotheses:
        lines = ["HIPÓTESIS (ordenadas por confianza):"]
        for i, h in enumerate(state.specialists.hypotheses[:3], 1):
            lines.append(f"{i}. {h}")
        sections.append("\n".join(lines))

    if not sections:
        return "", []

    structured = _SEP.join(sections)

    # Append outline hint if complexity is high
    if state.perception.complexity == "high" and key_points:
        outline = "OUTLINE SUGERIDO: [" + " → ".join(f"{i+1}. {kp[:40]}" for i, kp in enumerate(key_points[:3])) + "]"
        structured += _SEP + outline

    return structured, key_points


async def run_integration(state: BlackboardState) -> BlackboardState:
    """
    Run the full Reasoning/Integration Layer (F3 + F4).

    Steps:
      1. Logic check (F4): NLI consistency between hypotheses and facts
      2. Conflict resolution (F4): deterministic rules on version conflicts
      3. Build structured_answer
      4. Estimate confidence
      5. Decide escalation
    """
    t0 = time.monotonic()
    escalation_threshold, max_conflicts = _load_thresholds()

    # F4 Step 1: Logic check — hypotheses vs facts
    all_evidence = state.specialists.ranked_evidence or state.retrieval.weaviate_hits
    nli_conflicts: list[dict] = []
    if state.specialists.hypotheses and all_evidence:
        nli_conflicts = check_consistency(state.specialists.hypotheses, all_evidence)
        if nli_conflicts:
            logger.info("LogicChecker found %d NLI conflicts", len(nli_conflicts))

    # F4 Step 2: Conflict resolution — version conflicts + NLI conflicts
    all_hits = state.retrieval.weaviate_hits + state.retrieval.neo4j_hits
    resolved_conflicts, has_unresolved = resolve_conflicts(
        state.retrieval.version_conflicts,
        nli_conflicts,
        all_hits,
    )
    state.specialists.conflicts_found = resolved_conflicts

    # Build structured answer
    structured, key_points = _build_structured_answer(state)
    state.reasoning.structured_answer = structured
    state.reasoning.key_points = key_points

    # Estimate confidence
    query = state.specialists.rewritten_query or state.user_query
    evidence = state.specialists.ranked_evidence or state.retrieval.weaviate_hits
    confidence = estimate_confidence(query, evidence, state.retrieval.version_conflicts)
    state.reasoning.confidence_score = confidence

    # Escalation decision (F4: unresolved conflicts also trigger escalation)
    n_conflicts = len(state.retrieval.version_conflicts)
    should_escalate = (
        (confidence < escalation_threshold)
        or (n_conflicts > max_conflicts)
        or has_unresolved
    )
    state.reasoning.escalate_to_llm = should_escalate

    state.reasoning.reasoning_summary = (
        f"confidence={confidence:.2f} | conflicts={n_conflicts} | "
        f"nli_conflicts={len(nli_conflicts)} | unresolved={has_unresolved} | "
        f"evidence={len(evidence)} | escalate={should_escalate}"
    )

    elapsed = round((time.monotonic() - t0) * 1000, 2)
    state.latency_ms["reasoning"] = elapsed
    state.execution_trace.append({"layer": "reasoning", "latency_ms": elapsed})

    logger.info(
        "Integration done in %.1fms — confidence=%.2f escalate=%s conflicts=%d",
        elapsed, confidence, should_escalate, n_conflicts,
    )
    return state
