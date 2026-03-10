"""
Conflict Resolver — resolves version and NLI conflicts using deterministic rules.

Strategy (F4, no fine-tuning):
  1. NLI detects contradiction between two claims.
  2. Deterministic rules decide which one wins:
     - Rule 1: More recent source date wins (prefer latest year)
     - Rule 2: 'vigente' flag in Neo4j wins over 'obsoleto'
     - Rule 3: Higher retrieval score wins (more semantically relevant)
     - Rule 4: If rules are tied → mark as unresolved (escalate_to_llm)

Input:  state.retrieval.version_conflicts + state.specialists.conflicts_found
Output: state.specialists.conflicts_found (annotated with resolution)
        state.reasoning.escalate_to_llm = True if any unresolved

This module is pure Python logic — no ML model needed.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

_YEAR_RE = re.compile(r"\b(20\d{2})\b")


def _extract_year(text: str) -> Optional[int]:
    m = _YEAR_RE.search(text or "")
    return int(m.group(1)) if m else None


def _source_year(hit: dict) -> Optional[int]:
    """Extract year from hit text or metadata."""
    year = _extract_year(hit.get("text", ""))
    if year:
        return year
    meta = hit.get("metadata") or {}
    return _extract_year(str(meta.get("date", ""))) or _extract_year(str(meta.get("year", "")))


def _is_vigente(hit: dict) -> bool:
    text = hit.get("text", "").lower()
    meta = hit.get("metadata") or {}
    return "vigente" in text or meta.get("vigente") is True


def _is_obsoleto(hit: dict) -> bool:
    text = hit.get("text", "").lower()
    meta = hit.get("metadata") or {}
    return "obsoleto" in text or "deprecated" in text or meta.get("vigente") is False


def resolve_conflicts(
    version_conflicts: list[dict],
    nli_conflicts: list[dict],
    all_hits: list[dict],
) -> tuple[list[dict], bool]:
    """
    Apply deterministic resolution rules to all conflicts.

    Returns:
        (resolved_conflicts, has_unresolved)
        resolved_conflicts: each conflict annotated with 'resolution' and 'winner'
        has_unresolved:     True if any conflict could not be resolved → escalate
    """
    resolved: list[dict] = []
    has_unresolved = False

    # Resolve version conflicts
    for conflict in version_conflicts:
        resolution = _resolve_version_conflict(conflict, all_hits)
        resolved.append({**conflict, **resolution})
        if resolution["resolution"] == "unresolved":
            has_unresolved = True

    # Annotate NLI conflicts (already detected by LogicChecker)
    for conflict in nli_conflicts:
        # NLI conflicts: mark as flag for the generator, not auto-resolved
        resolved.append({
            **conflict,
            "resolution": "flagged",
            "winner": None,
            "note": "NLI inconsistency detected — generator should acknowledge uncertainty",
        })
        # NLI conflicts don't trigger escalation alone (confidence_score handles that)

    return resolved, has_unresolved


def _resolve_version_conflict(conflict: dict, all_hits: list[dict]) -> dict:
    """Apply rules to a single version conflict."""
    conflict_type = conflict.get("type", "")

    # --- Year discrepancy: prefer most recent year ---
    if conflict_type == "year_discrepancy":
        current_year = conflict.get("current_year")
        current_sources = conflict.get("current_sources", [])
        stale_year = conflict.get("stale_year")
        stale_sources = conflict.get("stale_sources", [])

        if current_year and stale_year and current_year > stale_year:
            return {
                "resolution": "rule_recency",
                "winner": "current",
                "winner_year": current_year,
                "winner_sources": current_sources,
                "loser_sources": stale_sources,
                "note": f"Year {current_year} is more recent than {stale_year} — preferring current.",
            }

    # --- Vigente conflict: prefer vigente over obsoleto ---
    if conflict_type == "vigente_conflict":
        vigente_sources = conflict.get("vigente_sources", [])
        stale_sources = conflict.get("stale_sources", [])
        if vigente_sources:
            return {
                "resolution": "rule_vigente",
                "winner": "vigente",
                "winner_sources": vigente_sources,
                "loser_sources": stale_sources,
                "note": "Preferring 'vigente' source over 'obsoleto/deprecated'.",
            }

    # --- Score-based: higher retrieval score wins ---
    if all_hits:
        sorted_hits = sorted(all_hits, key=lambda h: h.get("score", 0.0), reverse=True)
        top_hit = sorted_hits[0]
        top_source = top_hit.get("source", "")
        return {
            "resolution": "rule_score",
            "winner": top_source,
            "note": f"Highest retrieval score source used: {top_source} ({top_hit.get('score', 0):.2f})",
        }

    # --- Unresolved: escalate ---
    return {
        "resolution": "unresolved",
        "winner": None,
        "note": "No deterministic rule could resolve this conflict — escalating to LLM API.",
    }
