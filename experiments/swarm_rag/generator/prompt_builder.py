"""
Prompt Builder — constructs the final verbalization prompt from the blackboard.

The prompt is tone-aware: formal/technical/casual/neutral variants of the
system instruction. The SLM receives the structured_answer (already processed)
and must ONLY verbalize it — not reason, not retrieve, not invent.

Reads SLM parameters from config/thresholds.yaml.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

try:
    import yaml as _yaml
    _YAML_OK = True
except ImportError:
    _YAML_OK = False

from experiments.swarm_rag.schemas.blackboard_schema import BlackboardState

_THRESHOLDS_PATH = Path(__file__).parent.parent / "config" / "thresholds.yaml"

# ---------------------------------------------------------------------------
# Tone-specific system instructions
# ---------------------------------------------------------------------------

_SYSTEM_PROMPTS = {
    "formal": (
        "Eres un asistente experto. Tu única tarea es redactar una respuesta "
        "clara, precisa y bien estructurada basándote EXCLUSIVAMENTE en el contexto "
        "proporcionado. Usa un tono formal y profesional. "
        "No inventes información. Si algo no está en el contexto, indícalo explícitamente."
    ),
    "technical": (
        "Eres un asistente técnico especializado. Redacta una respuesta técnica "
        "y precisa usando EXCLUSIVAMENTE el contexto proporcionado. "
        "Incluye detalles técnicos relevantes. No especules más allá del contexto."
    ),
    "casual": (
        "Eres un asistente amigable. Responde de forma clara y natural "
        "usando EXCLUSIVAMENTE la información del contexto. "
        "Sé conciso y directo. No inventes datos."
    ),
    "neutral": (
        "Eres un asistente útil. Responde usando EXCLUSIVAMENTE el contexto "
        "proporcionado. Si no hay información suficiente, indícalo claramente."
    ),
}

_VERBALIZER_TEMPLATE = """\
{system_instruction}

CONTEXTO PROCESADO POR EL SISTEMA:
{evidence}

PREGUNTA ORIGINAL:
{query}

{outline_hint}RESPUESTA:"""

_FALLBACK_RESPONSE = (
    "No encontré información suficiente en el contexto disponible "
    "para responder esta pregunta con precisión."
)


def build_prompt(state: BlackboardState) -> tuple[str, str]:
    """
    Build the system prompt and user message for the SLM.

    Returns:
        (system_prompt, user_message) — ready to pass to chat([...])
    """
    tone = state.perception.tone or "neutral"
    system_prompt = _SYSTEM_PROMPTS.get(tone, _SYSTEM_PROMPTS["neutral"])

    evidence = state.reasoning.structured_answer or ""
    query = state.user_query

    # Outline hint (only for high-complexity queries with key_points)
    outline_hint = ""
    if state.perception.complexity == "high" and state.reasoning.key_points:
        pts = state.reasoning.key_points[:3]
        outline_hint = (
            "OUTLINE SUGERIDO: " +
            " → ".join(f"{i+1}. {p[:50]}" for i, p in enumerate(pts)) +
            "\n\n"
        )

    # Add confidence notice if escalation was triggered
    if state.reasoning.escalate_to_llm:
        confidence_note = (
            f"\n\n[NOTA: confianza del sistema = {state.reasoning.confidence_score:.0%}. "
            "Verifica con fuentes adicionales si es necesario.]"
        )
        evidence = evidence + confidence_note if evidence else confidence_note

    user_message = _VERBALIZER_TEMPLATE.format(
        system_instruction=system_prompt,
        evidence=evidence or "(Sin contexto recuperado)",
        query=query,
        outline_hint=outline_hint,
    )

    return system_prompt, user_message


def load_generator_params() -> dict:
    """Load SLM generation parameters from thresholds.yaml."""
    defaults = {
        "temperature": 0.3,
        "top_p": 0.9,
        "max_tokens": 1024,
    }
    if not _YAML_OK or not _THRESHOLDS_PATH.exists():
        return defaults
    try:
        data = _yaml.safe_load(_THRESHOLDS_PATH.read_text())
        g = data.get("generator", {})
        return {
            "temperature": float(g.get("temperature", defaults["temperature"])),
            "top_p": float(g.get("top_p", defaults["top_p"])),
            "max_tokens": int(g.get("max_tokens", defaults["max_tokens"])),
        }
    except Exception:
        return defaults
