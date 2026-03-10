"""
Evidence Merger plugin — fuses all layer outputs into evidence_summary.

Reads from the v3 blackboard schema:
  state.retrieval.*       — Knowledge Layer hits
  state.specialists.*     — Specialist Layer outputs
  state.retrieval.version_conflicts — conflicts

Writes to:
  state.reasoning.structured_answer (via reasoning layer in F2+)
  state.specialists.ranked_evidence is the input for reasoning

For F1: writes directly to state.reasoning.structured_answer as a
template-based string for the SLM to verbalize.
"""
from __future__ import annotations

import logging

from swarm_rag.plugins.base_plugin import BasePlugin
from swarm_rag.schemas.blackboard_schema import BlackboardState

logger = logging.getLogger(__name__)

_SEP = "\n" + "─" * 60 + "\n"


def _format_hits(hits: list[dict], label: str) -> str:
    if not hits:
        return ""
    lines = [f"### {label}"]
    for i, hit in enumerate(hits, 1):
        score = hit.get("score", 0.0)
        source = hit.get("source", "")
        text = hit.get("text", "").strip()
        header = f"[{i}]"
        if source:
            header += f" {source}"
        header += f" (score={score:.2f})"
        lines.append(header)
        lines.append(text)
    return "\n".join(lines)


def _format_math(specialists) -> str:
    result = specialists.math_result
    if result is None:
        return ""
    return f"### RESULTADO MATEMÁTICO\nResultado: {result}"


def _format_code(specialists) -> str:
    analysis = specialists.code_analysis
    if not analysis:
        return ""
    lines = ["### ANÁLISIS DE CÓDIGO"]
    if analysis.get("language"):
        lines.append(f"Lenguaje: {analysis['language']}")
    if analysis.get("result"):
        lines.append(f"Resultado:\n{analysis['result']}")
    if analysis.get("issues"):
        lines.append("Problemas: " + "; ".join(analysis["issues"]))
    return "\n".join(lines)


def _format_conflicts(conflicts: list[dict]) -> str:
    if not conflicts:
        return ""
    lines = ["### CONFLICTOS DE VERSIÓN"]
    for c in conflicts:
        lines.append(f"- {c.get('description', str(c))}")
    return "\n".join(lines)


def _format_hypotheses(hypotheses: list[str]) -> str:
    if not hypotheses:
        return ""
    lines = ["### HIPÓTESIS"]
    for i, h in enumerate(hypotheses, 1):
        lines.append(f"{i}. {h}")
    return "\n".join(lines)


class EvidenceMerger(BasePlugin):
    name = "evidence_merger"
    capabilities = ["evidence_fusion", "context_preparation"]
    inputs = ["retrieval", "specialists"]
    outputs = ["reasoning.structured_answer"]
    dependencies = ["context_compressor"]

    async def run(self, state: BlackboardState) -> BlackboardState:
        sections: list[str] = []

        # 1. Retrieved facts
        all_hits = state.retrieval.weaviate_hits + state.retrieval.neo4j_hits
        docs = _format_hits(all_hits, "HECHOS RECUPERADOS")
        if docs:
            sections.append(docs)

        # 2. Memory
        mem = _format_hits(state.retrieval.memory_hits, "MEMORIA DE SESIÓN")
        if mem:
            sections.append(mem)

        # 3. Math result
        math = _format_math(state.specialists)
        if math:
            sections.append(math)

        # 4. Code analysis
        code = _format_code(state.specialists)
        if code:
            sections.append(code)

        # 5. Version conflicts
        conflicts = _format_conflicts(state.retrieval.version_conflicts)
        if conflicts:
            sections.append(conflicts)

        # 6. Hypotheses (populated in F3+)
        hyp = _format_hypotheses(state.specialists.hypotheses)
        if hyp:
            sections.append(hyp)

        structured = _SEP.join(sections) if sections else ""
        state.reasoning.structured_answer = structured

        logger.info(
            "EvidenceMerger: %d sections, %d chars",
            len(sections), len(structured),
        )
        return state
