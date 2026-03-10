"""
SLM Verbalizer — the ONLY component that calls the local LM Studio / Ollama.

Wires into the existing project's ChatInterface via ProviderFactory.
Receives state.reasoning.structured_answer (already processed by reasoning layer)
and produces state.final_response.

If escalate_to_llm is True, delegates to llm_api_client instead.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import time
from typing import Any, Optional

from experiments.swarm_rag.schemas.blackboard_schema import BlackboardState
from experiments.swarm_rag.generator.prompt_builder import build_prompt, load_generator_params, _FALLBACK_RESPONSE

logger = logging.getLogger(__name__)


class SLMVerbalizer:
    """
    Verbalizes the blackboard's structured_answer using the local SLM.

    Args:
        chat_interface:  An object implementing ChatInterface.chat(messages) -> str.
                         Typically obtained via ProviderFactory(config).chat().
        llm_api_client:  Optional fallback for escalated queries (Claude/DeepSeek API).
                         Same interface as chat_interface.
    """

    def __init__(
        self,
        chat_interface: Any,
        llm_api_client: Optional[Any] = None,
    ) -> None:
        self._chat = chat_interface
        self._llm_api = llm_api_client
        self._params = load_generator_params()

    async def run(self, state: BlackboardState) -> BlackboardState:
        if not state.reasoning.structured_answer:
            logger.warning("SLMVerbalizer: no structured_answer — returning fallback")
            state.final_response = _FALLBACK_RESPONSE
            return state

        # Escalation: use LLM API when confidence is low
        if state.reasoning.escalate_to_llm and self._llm_api is not None:
            logger.info(
                "SLMVerbalizer: escalating to LLM API (confidence=%.2f)",
                state.reasoning.confidence_score,
            )
            return await self._verbalize(state, self._llm_api)

        return await self._verbalize(state, self._chat)

    async def _verbalize(self, state: BlackboardState, interface: Any) -> BlackboardState:
        system_prompt, user_message = build_prompt(state)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        t0 = time.monotonic()
        try:
            result = interface.chat(
                messages,
                temperature=self._params["temperature"],
                max_tokens=self._params["max_tokens"],
            )
            if inspect.isawaitable(result):
                result = await result
            state.final_response = (result or "").strip() or _FALLBACK_RESPONSE
        except Exception as exc:
            logger.error("SLMVerbalizer call failed: %s", exc, exc_info=True)
            state.final_response = _FALLBACK_RESPONSE

        elapsed = round((time.monotonic() - t0) * 1000, 2)
        state.latency_ms["generator"] = elapsed
        state.execution_trace.append({"layer": "generator", "latency_ms": elapsed})
        logger.info("SLMVerbalizer done in %.1fms", elapsed)
        return state
