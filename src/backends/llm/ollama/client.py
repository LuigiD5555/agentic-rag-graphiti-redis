"""
OllamaChat — implements ChatInterface against POST /api/chat.

Ollama chat API:
  POST /api/chat
  Body:     {"model": "...", "messages": [...], "stream": false, "options": {"temperature": ...}}
  Response: {"message": {"role": "assistant", "content": "..."}, ...}

ttl parameter is part of the ChatInterface protocol but has no meaning for Ollama — ignored.
No retry loop needed: Ollama keeps models resident and has no transient load errors.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Dict, List, Optional

import requests

from src.utils.structured_log import emit_structured_log
from src.workflows.query.interfaces.chat_interface import ChatInterface

logger = logging.getLogger(__name__)


class OllamaChat(ChatInterface):
    def __init__(
        self,
        base_url: str,
        model: str = "llama3.2",
        temperature: float = 0.7,
        require_live: bool = False,
        timeout: int = 120,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/api/chat"
        self.model = model
        self._temperature = temperature
        self._require_live = require_live
        self._timeout = timeout
        logger.info("OllamaChat init (model=%s, url=%s)", model, self._url)

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        request_id: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> str:
        selected_model = model or self.model
        temp = temperature if temperature is not None else self._temperature
        request_id = request_id or f"ollama-chat-{uuid.uuid4().hex[:12]}"

        payload: Dict = {
            "model": selected_model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temp},
        }
        if max_tokens is not None:
            payload["options"]["num_predict"] = max_tokens

        try:
            t0 = time.perf_counter()
            emit_structured_log(
                logger,
                component="ollama_client",
                request_id=request_id,
                operation="chat_start",
                model_name=selected_model,
                messages_count=len(messages),
            )
            resp = requests.post(self._url, json=payload, timeout=self._timeout)
            resp.raise_for_status()
            text = resp.json().get("message", {}).get("content", "").strip()
            emit_structured_log(
                logger,
                component="ollama_client",
                request_id=request_id,
                operation="chat_end",
                model_name=selected_model,
                duration_ms=(time.perf_counter() - t0) * 1000,
                response_chars=len(text),
            )
            return text
        except requests.exceptions.RequestException as exc:
            logger.error("Ollama chat error: %s", exc)
            emit_structured_log(
                logger,
                component="ollama_client",
                request_id=request_id,
                operation="chat_error",
                model_name=selected_model,
                error=str(exc),
            )
            if self._require_live:
                raise RuntimeError(f"Ollama chat failed: {exc}") from exc
            return ""

    def complete(
        self,
        prompt: str,
        max_tokens: int = 256,
        request_id: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> str:
        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt},
        ]
        return self.chat(messages, max_tokens=max_tokens, request_id=request_id)
