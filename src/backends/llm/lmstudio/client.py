"""Module with services that communicate RAG requests to LM Studio API."""
import requests
import time
import uuid
from typing import List, Dict, Optional
from src import logger
from src.utils.structured_log import emit_structured_log


class LLMService:
    """
    Service to get completions from LM Studio using OpenAI-compatible API.
    Uses ModelManager to select the first available non-embedding model.
    """

    def __init__(self, config, model_manager, temperature: float = 0.7):
        """
        Initialize LLMService with LM Studio endpoint and selected model.
        """
        roots = getattr(config, "LMSTUDIO_API_ROOTS", [f"http://{config.LMSTUDIO_HOST}:{config.LMSTUDIO_PORT}"])
        preferred_root = model_manager.api_root or roots[0]
        self._candidate_roots = []
        for root in [preferred_root, *roots]:
            root_norm = root.rstrip("/")
            if root_norm not in self._candidate_roots:
                self._candidate_roots.append(root_norm)

        self.api_root = self._candidate_roots[0]
        self.url = f"{self.api_root}/v1/chat/completions"
        self._require_live = bool(getattr(config, "LMSTUDIO_REQUIRE_SERVER", False))

        explicit_model = getattr(config, "LMSTUDIO_CHAT_MODEL", None)
        if explicit_model:
            self.model = explicit_model
        else:
            self.model = model_manager.get_first_language_model() or "gpt-3.5-turbo"
        self.temperature = temperature

        logger.info("Selected LLM model: %s", self.model)

    def complete(
        self,
        prompt: str,
        max_tokens: int = 256,
        request_id: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> str:
        """
        Request chat completion from LM Studio using the selected LLM model.
        """
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ],
            "temperature": self.temperature,
            "max_tokens": max_tokens
        }
        if ttl is not None:
            payload["ttl"] = ttl
        request_id = request_id or f"chat-{uuid.uuid4().hex[:12]}"

        for root in self._candidate_roots:
            url = f"{root}/v1/chat/completions"
            try:
                started = time.perf_counter()
                emit_structured_log(
                    logger,
                    component="lmstudio_client",
                    request_id=request_id,
                    operation="chat_request_start",
                    model_name=self.model,
                    endpoint=url,
                    payload_keys=sorted(payload.keys()),
                    payload_summary={
                        "model": payload.get("model"),
                        "max_tokens": payload.get("max_tokens"),
                        "temperature": payload.get("temperature"),
                        "messages_count": len(payload.get("messages", [])),
                    },
                    ttl=payload.get("ttl"),
                )
                logger.info(
                    "Sending chat completion to LM Studio (model=%s, host=%s, max_tokens=%d)...",
                    self.model,
                    root,
                    max_tokens,
                )
                response = requests.post(url, json=payload, timeout=30)
                response.raise_for_status()

                data = response.json()
                text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

                if not text:
                    logger.warning("LM Studio returned an empty chat completion response.")
                else:
                    logger.info("Received chat completion response (%d chars).", len(text))
                emit_structured_log(
                    logger,
                    component="lmstudio_client",
                    request_id=request_id,
                    operation="chat_request_end",
                    model_name=self.model,
                    duration_ms=(time.perf_counter() - started) * 1000.0,
                    endpoint=url,
                    status_code=response.status_code,
                    response_chars=len(text),
                )

                self.api_root = root
                self.url = url
                return text

            except requests.exceptions.RequestException as e:
                logger.error("Failed to connect to LM Studio for chat completion (%s): %s", root, e)
                emit_structured_log(
                    logger,
                    component="lmstudio_client",
                    request_id=request_id,
                    operation="chat_request_error",
                    model_name=self.model,
                    endpoint=url,
                    error=str(e),
                )

        logger.error("All LM Studio completion endpoints failed: %s", self._candidate_roots)
        if self._require_live:
            raise RuntimeError(
                "LM Studio chat completions required but no endpoint responded. "
                f"Tried: {self._candidate_roots}"
            )
        return ""

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        request_id: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> str:
        """
        Send chat completion request with message history.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            temperature: Override default temperature.
            max_tokens: Override default max_tokens.
            model: Override default model.

        Returns:
            Generated response text.
        """
        temp = temperature if temperature is not None else self.temperature
        tokens = max_tokens if max_tokens is not None else 256
        selected_model = model if model is not None else self.model

        payload = {
            "model": selected_model,
            "messages": messages,
            "temperature": temp,
            "max_tokens": tokens,
        }
        if ttl is not None:
            payload["ttl"] = ttl
        request_id = request_id or f"chat-{uuid.uuid4().hex[:12]}"

        for root in self._candidate_roots:
            url = f"{root}/v1/chat/completions"
            try:
                started = time.perf_counter()
                emit_structured_log(
                    logger,
                    component="lmstudio_client",
                    request_id=request_id,
                    operation="chat_request_start",
                    model_name=selected_model,
                    endpoint=url,
                    payload_keys=sorted(payload.keys()),
                    payload_summary={
                        "model": payload.get("model"),
                        "max_tokens": payload.get("max_tokens"),
                        "temperature": payload.get("temperature"),
                        "messages_count": len(payload.get("messages", [])),
                    },
                    ttl=payload.get("ttl"),
                )
                logger.info(
                    "Sending chat request to LM Studio (model=%s, host=%s, %d messages, max_tokens=%d)...",
                    selected_model,
                    root,
                    len(messages),
                    tokens,
                )
                response = requests.post(url, json=payload, timeout=30)
                response.raise_for_status()

                data = response.json()
                text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

                if not text:
                    logger.warning("LM Studio returned an empty chat response.")
                else:
                    logger.info("Received chat response (%d chars).", len(text))
                emit_structured_log(
                    logger,
                    component="lmstudio_client",
                    request_id=request_id,
                    operation="chat_request_end",
                    model_name=selected_model,
                    duration_ms=(time.perf_counter() - started) * 1000.0,
                    endpoint=url,
                    status_code=response.status_code,
                    response_chars=len(text),
                )

                self.api_root = root
                self.url = url
                return text

            except requests.exceptions.RequestException as e:
                logger.error("Failed to connect to LM Studio for chat (%s): %s", root, e)
                emit_structured_log(
                    logger,
                    component="lmstudio_client",
                    request_id=request_id,
                    operation="chat_request_error",
                    model_name=selected_model,
                    endpoint=url,
                    error=str(e),
                )

        logger.error("All LM Studio chat endpoints failed: %s", self._candidate_roots)
        if self._require_live:
            raise RuntimeError(
                "LM Studio chat required but no endpoint responded. "
                f"Tried: {self._candidate_roots}"
            )
        return ""
