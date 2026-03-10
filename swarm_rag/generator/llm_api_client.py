"""
LLM API Client — escalation target when confidence_score < threshold.

Implements the same chat(messages) -> str interface as the local SLM clients.
Default target: Claude Haiku (fast + cheap). Configurable via env vars.

SWARM_LLM_API_PROVIDER: 'anthropic' (default) | 'openai' | 'deepseek'
SWARM_LLM_API_MODEL:    model ID (default depends on provider)
SWARM_LLM_API_KEY:      API key (falls back to ANTHROPIC_API_KEY / OPENAI_API_KEY)
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_PROVIDER = os.getenv("SWARM_LLM_API_PROVIDER", "anthropic").lower()
_MODEL_DEFAULTS = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai": "gpt-4o-mini",
    "deepseek": "deepseek-chat",
}


class LLMApiClient:
    """
    Thin wrapper for LLM API escalation. Satisfies the ChatInterface protocol.

    Only used when state.reasoning.escalate_to_llm is True.
    If the API call fails, returns an empty string (SLMVerbalizer uses fallback).
    """

    def __init__(
        self,
        provider: str = _PROVIDER,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> None:
        self._provider = provider
        self._model = model or _MODEL_DEFAULTS.get(provider, "claude-haiku-4-5-20251001")
        self._api_key = api_key or self._resolve_key(provider)
        logger.info("LLMApiClient: provider=%s model=%s", provider, self._model)

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.3,
        max_tokens: int = 1024,
        **kwargs,
    ) -> str:
        if not self._api_key:
            logger.warning("LLMApiClient: no API key — skipping escalation")
            return ""
        try:
            if self._provider == "anthropic":
                return self._call_anthropic(messages, temperature, max_tokens)
            if self._provider in ("openai", "deepseek"):
                return self._call_openai_compat(messages, temperature, max_tokens)
            logger.warning("LLMApiClient: unknown provider '%s'", self._provider)
            return ""
        except Exception as exc:
            logger.error("LLMApiClient call failed: %s", exc, exc_info=True)
            return ""

    def complete(self, prompt: str, max_tokens: int = 256, **kwargs) -> str:
        messages = [{"role": "user", "content": prompt}]
        return self.chat(messages, max_tokens=max_tokens)

    # ------------------------------------------------------------------
    # Provider-specific calls
    # ------------------------------------------------------------------

    def _call_anthropic(self, messages: list[dict], temperature: float, max_tokens: int) -> str:
        import anthropic
        client = anthropic.Anthropic(api_key=self._api_key)
        # Separate system message (Anthropic API convention)
        system = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_msgs = [m for m in messages if m["role"] != "system"]
        response = client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system or "You are a helpful assistant.",
            messages=user_msgs,
        )
        return response.content[0].text.strip()

    def _call_openai_compat(self, messages: list[dict], temperature: float, max_tokens: int) -> str:
        from openai import OpenAI
        base_url = None
        if self._provider == "deepseek":
            base_url = "https://api.deepseek.com/v1"
        client = OpenAI(api_key=self._api_key, base_url=base_url)
        response = client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()

    @staticmethod
    def _resolve_key(provider: str) -> Optional[str]:
        key_map = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
        }
        env_var = key_map.get(provider, "ANTHROPIC_API_KEY")
        return os.getenv("SWARM_LLM_API_KEY") or os.getenv(env_var)
