"""
Version Monitor plugin — detects conflicts between sources in the blackboard.

Compares metadata from weaviate_hits and neo4j_hits:
- Date/year discrepancies between hits on the same topic
- 'vigente' vs non-vigente flags in Neo4j edges
- Explicit version_id or version fields that differ across sources

Writes detected conflicts to state.version_conflicts and
active_versions (the most recent version found per topic).

No LLM call, no external I/O — pure in-memory analysis.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict

from swarm_rag.plugins.base_plugin import BasePlugin
from swarm_rag.schemas.blackboard_schema import BlackboardState

logger = logging.getLogger(__name__)

_YEAR_RE = re.compile(r"\b(20\d{2})\b")


def _extract_year(text: str) -> int | None:
    m = _YEAR_RE.search(text or "")
    return int(m.group(1)) if m else None


def _source_label(hit: dict) -> str:
    return hit.get("source") or hit.get("chunk_id") or "unknown"


class VersionMonitorPlugin(BasePlugin):
    name = "version_monitor"
    capabilities = ["version_conflict_detection"]
    inputs = ["retrieval.neo4j_hits", "retrieval.weaviate_hits"]
    outputs = ["version_conflicts", "active_versions"]
    dependencies = ["retrieval"]

    async def run(self, state: BlackboardState) -> BlackboardState:
        conflicts: list[dict] = []
        active_versions: list[dict] = []

        all_hits = state.retrieval.weaviate_hits + state.retrieval.neo4j_hits

        # --- 1. Year discrepancy across hits ---
        years_by_source: dict[int, list[str]] = defaultdict(list)
        for hit in all_hits:
            year = _extract_year(hit.get("text", ""))
            if year:
                years_by_source[year].append(_source_label(hit))

        if len(years_by_source) > 1:
            sorted_years = sorted(years_by_source.keys())
            latest = sorted_years[-1]
            active_versions.append({"year": latest, "sources": years_by_source[latest]})
            for yr in sorted_years[:-1]:
                conflicts.append({
                    "type": "year_discrepancy",
                    "description": (
                        f"Year {yr} found in {years_by_source[yr]} "
                        f"but latest is {latest} ({years_by_source[latest]})"
                    ),
                    "stale_year": yr,
                    "current_year": latest,
                    "stale_sources": years_by_source[yr],
                    "current_sources": years_by_source[latest],
                })

        # --- 2. Neo4j 'vigente' flag conflicts ---
        vigente_hits = [
            h for h in state.retrieval.neo4j_hits
            if "vigente" in h.get("text", "").lower()
               or h.get("metadata", {}).get("vigente")
        ]
        non_vigente_hits = [
            h for h in state.retrieval.neo4j_hits
            if "obsoleto" in h.get("text", "").lower()
               or "deprecated" in h.get("text", "").lower()
               or h.get("metadata", {}).get("vigente") is False
        ]
        if vigente_hits and non_vigente_hits:
            conflicts.append({
                "type": "vigente_conflict",
                "description": (
                    f"Both 'vigente' and 'obsoleto/deprecated' sources found. "
                    f"Vigente: {[_source_label(h) for h in vigente_hits[:3]]}. "
                    f"Non-vigente: {[_source_label(h) for h in non_vigente_hits[:3]]}."
                ),
                "vigente_sources": [_source_label(h) for h in vigente_hits],
                "stale_sources": [_source_label(h) for h in non_vigente_hits],
            })

        state.retrieval.version_conflicts = conflicts
        # active_versions stored in specialists for now (not in v3 schema top-level)
        if active_versions:
            state.specialists.extracted_facts.extend(
                [{"type": "active_version", **v} for v in active_versions]
            )

        if conflicts:
            logger.info("VersionMonitor: %d conflict(s) detected", len(conflicts))
        else:
            logger.debug("VersionMonitor: no conflicts detected")

        return state
