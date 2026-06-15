"""
SLM Verbalizer — the ONLY module that calls LM Studio.

Receives an already-processed evidence_summary from the Evidence Merger
and produces the final natural-language response. The SLM does NOT
retrieve, reason, or invent; it only verbalizes what the system prepared.

Integrates with the existing LLMService in src/backends/llm/lmstudio/client.py
via the project's ProviderFactory so that concurrency limits, retries, and
fallback logic defined there are transparently applied.
"""
from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

from experiments.swarm_rag.plugins.base_plugin import BasePlugin
from experiments.swarm_rag.schemas.blackboard_schema import BlackboardState

if TYPE_CHECKING:
    # Avoid circular import at module load; injected at runtime
    from src.workflows.query.interfaces.chat_interface import ChatInterface

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt template
# ---------------------------------------------------------------------------

VERBALIZER_PROMPT = """\
Eres un asistente experto. A continuación tienes el contexto ya procesado \
y verificado por el sistema de análisis.

Tu única tarea es redactar una respuesta clara, completa y bien estructurada \
usando EXCLUSIVAMENTE este contexto.

No inventes información. Si algo no está en el contexto, indica que no se \
encontró información suficiente.

CONTEXTO PROCESADO:
{evidence_summary}

PREGUNTA ORIGINAL:
{user_query}

RESPUESTA:"""

_FALLBACK_RESPONSE = (
    "No encontré información suficiente en el contexto disponible para "
    "responder esta pregunta con precisión."
)

# Recommended verbalizer parameters (low temperature — SLM must not hallucinate)
_DEFAULT_TEMPERATURE = 0.3
_DEFAULT_MAX_TOKENS = 1024


class SLMVerbalizer(BasePlugin):
    """
    Terminal plugin that verbalizes the evidence_summary via LM Studio.

    Must be injected with a ChatInterface (or any object implementing
    `chat(messages) -> str`) at construction time.
    """

    name = "slm_verbalizer"
    capabilities = ["verbalization", "response_generation"]
    inputs = ["evidence_summary", "user_query"]
    outputs = ["final_response"]
    dependencies = ["evidence_merger"]

    def __init__(
        self,
        chat_interface: "ChatInterface",
        temperature: float = _DEFAULT_TEMPERATURE,
        max_tokens: int = _DEFAULT_MAX_TOKENS,
    ) -> None:
        self._chat = chat_interface
        self._temperature = temperature
        self._max_tokens = max_tokens

    async def run(self, state: BlackboardState) -> BlackboardState:
        if not state.evidence_summary:
            logger.warning("SLMVerbalizer: no evidence_summary — returning fallback")
            state.final_response = _FALLBACK_RESPONSE
            return state

        prompt = VERBALIZER_PROMPT.format(
            evidence_summary=state.evidence_summary,
            user_query=state.user_query,
        )
        messages = [{"role": "user", "content": prompt}]

        try:
            response = await self._call_llm(messages)
            state.final_response = response.strip() if response else _FALLBACK_RESPONSE
        except Exception as exc:
            logger.error("SLMVerbalizer LLM call failed: %s", exc, exc_info=True)
            state.final_response = _FALLBACK_RESPONSE

        return state

    async def _call_llm(self, messages: list[dict]) -> Optional[str]:
        """
        Delegate to the injected ChatInterface.

        The interface may be synchronous (LLMService.chat) or async;
        we handle both cases transparently.
        """
        import asyncio
        import inspect

        result = self._chat.chat(messages)
        if inspect.isawaitable(result):
            return await result
        return result
