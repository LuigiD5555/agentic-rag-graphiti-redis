"""
OllamaEmbeddingService — generate embeddings via POST /api/embeddings.

Ollama embedding API:
  POST /api/embeddings
  Body:     {"model": "nomic-embed-text", "prompt": "<text>"}
  Response: {"embedding": [float, ...]}
"""
from __future__ import annotations

import math
import time
import uuid
import logging
from typing import List, Optional

import requests

from src.utils.structured_log import emit_structured_log

logger = logging.getLogger(__name__)


class OllamaEmbeddingService:
    """Implements EmbeddingInterface against Ollama /api/embeddings."""

    def __init__(
        self,
        base_url: str,
        model_name: str,
        expected_dim: int,
        require_live: bool = False,
        timeout: int = 120,
    ) -> None:
        self._url = f"{base_url.rstrip('/')}/api/embeddings"
        self._model_name = model_name
        self._expected_dim = expected_dim
        self._require_live = require_live
        self._timeout = timeout
        self._session = requests.Session()
        logger.info("OllamaEmbeddingService init (model=%s, dim=%d)", model_name, expected_dim)

    def generate(
        self,
        text: str,
        source: Optional[str] = None,
        chunk_index: Optional[int] = None,
        request_id: Optional[str] = None,
    ) -> List[float]:
        request_id = request_id or f"ollama-emb-{uuid.uuid4().hex[:12]}"
        payload = {"model": self._model_name, "prompt": text}
        try:
            t0 = time.perf_counter()
            emit_structured_log(
                logger,
                component="ollama_embedding",
                request_id=request_id,
                operation="embedding_start",
                model_name=self._model_name,
                input_chars=len(text),
            )
            resp = self._session.post(self._url, json=payload, timeout=self._timeout)
            resp.raise_for_status()
            raw = resp.json().get("embedding")
            if raw is None:
                raise ValueError("Ollama /api/embeddings returned no 'embedding' key")
            vector = self._validate(raw)
            emit_structured_log(
                logger,
                component="ollama_embedding",
                request_id=request_id,
                operation="embedding_end",
                model_name=self._model_name,
                duration_ms=(time.perf_counter() - t0) * 1000,
                embedding_dim=len(vector),
            )
            return vector
        except requests.exceptions.RequestException as exc:
            logger.error("Ollama embedding HTTP error: %s", exc)
            if self._require_live:
                raise RuntimeError(f"Ollama embeddings failed: {exc}") from exc
            return self._dummy()
        except (ValueError, TypeError) as exc:
            logger.error("Invalid Ollama embedding response: %s", exc)
            if self._require_live:
                raise
            return self._dummy()

    def _validate(self, vector) -> List[float]:
        if not isinstance(vector, (list, tuple)):
            raise TypeError(f"Embedding must be a list, got {type(vector)}")
        if len(vector) != self._expected_dim:
            raise ValueError(
                f"Embedding dim mismatch: expected {self._expected_dim}, got {len(vector)}"
            )
        out: List[float] = []
        for i, v in enumerate(vector):
            try:
                f = float(v)
            except (TypeError, ValueError) as exc:
                raise TypeError(f"Non-numeric at index {i}: {v!r}") from exc
            if not math.isfinite(f):
                raise ValueError(f"Non-finite at index {i}: {f!r}")
            out.append(f)
        return out

    def _dummy(self) -> List[float]:
        return [0.0] * self._expected_dim
