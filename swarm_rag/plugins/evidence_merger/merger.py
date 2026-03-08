"""
Evidence Merger plugin — fuses all plugin outputs into a single evidence_summary.

Phase 1 (current): template-based with fixed sections.
Only sections with data are included. Output is a plain string that the
SLM Verbalizer receives as its sole context.

Section order (when data present):
  1. HECHOS RECUPERADOS      ← weaviate + neo4j hits
  2. MEMORIA DE SESIÓN       ← memory hits
  3. RESULTADO MATEMÁTICO    ← math_context.result
  4. ANÁLISIS DE CÓDIGO      ← code_context.result
  5. CONFLICTOS DE VERSIÓN   ← version_conflicts
  6. RESULTADOS DE TOOLS     ← tool_results
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


def _format_math(math_ctx) -> str:
    if not math_ctx.detected:
        return ""
    lines = ["### RESULTADO MATEMÁTICO"]
    if math_ctx.problem_type:
        lines.append(f"Tipo: {math_ctx.problem_type}")
    if math_ctx.result is not None:
        lines.append(f"Resultado: {math_ctx.result}")
    if math_ctx.missing_inputs:
        lines.append(f"Datos faltantes: {', '.join(math_ctx.missing_inputs)}")
    return "\n".join(lines)


def _format_code(code_ctx) -> str:
    if not code_ctx.detected:
        return ""
    lines = ["### ANÁLISIS DE CÓDIGO"]
    if code_ctx.language:
        lines.append(f"Lenguaje: {code_ctx.language}")
    if code_ctx.task_type:
        lines.append(f"Tarea: {code_ctx.task_type}")
    if code_ctx.result is not None:
        lines.append(f"Resultado:\n{code_ctx.result}")
    if code_ctx.issues:
        lines.append("Problemas detectados: " + "; ".join(code_ctx.issues))
    return "\n".join(lines)


def _format_conflicts(conflicts: list[dict]) -> str:
    if not conflicts:
        return ""
    lines = ["### CONFLICTOS DE VERSIÓN"]
    for c in conflicts:
        desc = c.get("description") or str(c)
        lines.append(f"- {desc}")
    return "\n".join(lines)


def _format_tool_results(results: list[dict]) -> str:
    if not results:
        return ""
    lines = ["### RESULTADOS DE TOOLS"]
    for r in results:
        tool = r.get("tool", "tool")
        output = r.get("output") or str(r)
        lines.append(f"[{tool}] {output}")
    return "\n".join(lines)


class EvidenceMerger(BasePlugin):
    name = "evidence_merger"
    capabilities = ["evidence_fusion", "context_preparation"]
    inputs = ["retrieval", "math_context", "code_context", "version_conflicts"]
    outputs = ["evidence_summary"]
    dependencies = ["context_compressor"]

    async def run(self, state: BlackboardState) -> BlackboardState:
        sections: list[str] = []

        # 1. Retrieved facts (weaviate + neo4j combined)
        all_hits = state.retrieval.weaviate_hits + state.retrieval.neo4j_hits
        docs_section = _format_hits(all_hits, "HECHOS RECUPERADOS")
        if docs_section:
            sections.append(docs_section)

        # 2. Session memory
        mem_section = _format_hits(state.retrieval.memory_hits, "MEMORIA DE SESIÓN")
        if mem_section:
            sections.append(mem_section)

        # 3. Math result
        math_section = _format_math(state.math_context)
        if math_section:
            sections.append(math_section)

        # 4. Code analysis
        code_section = _format_code(state.code_context)
        if code_section:
            sections.append(code_section)

        # 5. Version conflicts
        conflicts_section = _format_conflicts(state.version_conflicts)
        if conflicts_section:
            sections.append(conflicts_section)

        # 6. Tool results
        tools_section = _format_tool_results(state.tool_results)
        if tools_section:
            sections.append(tools_section)

        if sections:
            state.evidence_summary = _SEP.join(sections)
            logger.info("EvidenceMerger: %d sections, %d chars",
                        len(sections), len(state.evidence_summary))
        else:
            state.evidence_summary = ""
            logger.warning("EvidenceMerger: no evidence collected for query='%.60s…'",
                           state.user_query)

        return state
