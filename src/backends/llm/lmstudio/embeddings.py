"""
Module with services that generate embeddings using an LM Studio-compatible endpoint.

Key behaviors:
-   Object-oriented design.
-   No custom exceptions; only built-in and requests' exceptions are used.
-   Strong validation: ensures the returned embedding is a flat list[float],
    with exact dimensionality (from Config), and only finite values.
"""

import math
import time
import uuid
from typing import Any, Dict, List, Sequence, Optional
import requests
from requests import Response
from src import logger
from src.utils.structured_log import emit_structured_log


class EmbeddingService:
    """
    Service to generate embeddings using an LM Studio/OpenAI-compatible endpoint.
    Selects an embedding model via ModelManager and validates outputs thoroughly.
    """

    def __init__(self, config: Any, model_manager: Any) -> None:
        """
        Initialize EmbeddingService with endpoint and selected model.

        Expected Config attributes:
            -   LM_EMBED_URL: str -> base URL or full /v1/embeddings endpoint.
            -   EMBEDDING_DIM: int -> expected dimensionality for embeddings.
            -   EMBEDDING_MODEL: str -> REQUIRED explicit model name (e.g., text-embedding-nomic-embed-text-v2-moe).

        Model selection:
            -   EMBEDDING_MODEL must be explicitly configured in .env
            -   Automatic model selection has been removed to prevent configuration errors
            -   System will raise RuntimeError if EMBEDDING_MODEL is not set
        """
        api_roots = getattr(
            config,
            "LMSTUDIO_API_ROOTS",
            [config.LM_EMBED_URL.rsplit("/v1/embeddings", 1)[0]],
        )
        preferred_root = (model_manager.api_root or api_roots[0]).rstrip("/")
        self._candidate_roots: List[str] = []
        for root in [preferred_root, *api_roots]:
            root_norm = root.rstrip("/")
            if root_norm not in self._candidate_roots:
                self._candidate_roots.append(root_norm)

        self._api_root: str = self._candidate_roots[0]
        self._embed_url: str = f"{self._api_root}/v1/embeddings"
        self._require_live = bool(getattr(config, "LMSTUDIO_REQUIRE_SERVER", False))

        # Model selection - MUST be explicitly configured
        self._model_name: Optional[str] = getattr(config, "EMBEDDING_MODEL", None)
        if not self._model_name:
            raise RuntimeError(
                "EMBEDDING_MODEL must be explicitly configured in .env. "
                "Automatic model selection has been removed. "
                "Set EMBEDDING_MODEL to your preferred model (e.g., text-embedding-nomic-embed-text-v2-moe)"
            )

        self._use_dummy: bool = not bool(self._model_name)

        # Auto-detect embedding dimension from model name, fallback to config
        if self._model_name:
            detected_dim = model_manager.get_model_dimensions(self._model_name)
            if detected_dim:
                self._expected_dim = detected_dim
                logger.info("Auto-detected embedding dimension: %d for model: %s", detected_dim, self._model_name)
            else:
                # Fallback to config value if model dimensions unknown
                self._expected_dim = int(getattr(config, "EMBEDDING_DIM", 768))
                logger.warning(
                    "Could not auto-detect dimensions for model '%s', using configured EMBEDDING_DIM=%d",
                    self._model_name,
                    self._expected_dim
                )
        else:
            # No model available, use config dimension
            self._expected_dim = int(getattr(config, "EMBEDDING_DIM", 768))

        if self._use_dummy:
            if self._require_live:
                raise RuntimeError(
                    "LM Studio embedding model required but none available. "
                    "Ensure LM Studio is running and reports embedding models."
                )
            logger.warning("No embedding model found. Using dummy embeddings of size %d.", self._expected_dim)
        else:
            logger.info("Selected embedding model: %s (dimension: %d)", self._model_name, self._expected_dim)

        # Optional: a requests.Session could be used for connection pooling
        self._session = requests.Session()

    # ------------- Public API -------------

    def generate(
        self,
        text: str,
        source: Optional[str] = None,
        chunk_index: Optional[int] = None,
        request_id: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> List[float]:
        """
        Generate an embedding vector for the given text and return a validated list[float].

        Behavior:
            -   If no model is available, returns a zero vector of size EMBEDDING_DIM.
            -   If the HTTP call fails or the response schema is unexpected, logs and
                returns a dummy vector.
            -   If the provider returns an invalid vector (wrong dim, None/NaN/Inf),
                raises ValueError/TypeError.
        """
        if self._use_dummy:
            if self._require_live:
                raise RuntimeError("LM Studio embeddings required but service is in dummy mode.")
            return self._dummy_vector()

        payload = {"model": self._model_name, "input": text}
        if ttl is not None:
            payload["ttl"] = ttl
        request_id = request_id or f"embed-{uuid.uuid4().hex[:12]}"
        for root in self._candidate_roots:
            url = f"{root}/v1/embeddings"
            try:
                started = time.perf_counter()
                emit_structured_log(
                    logger,
                    component="lmstudio_embedding_client",
                    request_id=request_id,
                    operation="embedding_request_start",
                    model_name=self._model_name or "",
                    endpoint=url,
                    source=source,
                    chunk_index=chunk_index,
                    input_chars=len(text),
                    payload_keys=sorted(payload.keys()),
                    payload_summary={
                        "model": payload.get("model"),
                        "input_type": type(payload.get("input")).__name__,
                    },
                    ttl=payload.get("ttl"),
                )
                resp = self._post_json(url, payload, timeout=60)  # Max 1 minute
                data = self._to_json(resp)
                raw_vector = self._extract_vector(data)
                vector = self._normalize_and_validate_vector(raw_vector)
                self._api_root = root
                self._embed_url = url
                emit_structured_log(
                    logger,
                    component="lmstudio_embedding_client",
                    request_id=request_id,
                    operation="embedding_request_end",
                    model_name=self._model_name or "",
                    duration_ms=(time.perf_counter() - started) * 1000.0,
                    endpoint=url,
                    status_code=resp.status_code,
                    embedding_dim=len(vector),
                )
                return vector
            except requests.exceptions.RequestException as exc:
                logger.error("Embedding HTTP error (%s); attempting next endpoint: %s", root, exc)
                emit_structured_log(
                    logger,
                    component="lmstudio_embedding_client",
                    request_id=request_id,
                    operation="embedding_request_error",
                    model_name=self._model_name or "",
                    endpoint=url,
                    error=str(exc),
                )
                continue
            except (ValueError, TypeError) as exc:
                logger.error("Invalid embedding response; returning dummy vector: %s", exc)
                emit_structured_log(
                    logger,
                    component="lmstudio_embedding_client",
                    request_id=request_id,
                    operation="embedding_response_invalid",
                    model_name=self._model_name or "",
                    endpoint=url,
                    error=str(exc),
                )
                if self._require_live:
                    raise
                return self._dummy_vector()

        logger.error("All LM Studio embedding endpoints failed: %s", self._candidate_roots)
        if self._require_live:
            raise RuntimeError(
                "LM Studio embeddings required but every endpoint failed. "
                f"Tried: {self._candidate_roots}"
            )
        return self._dummy_vector()

    def generate_batch(
        self,
        texts: List[str],
        sources: Optional[List[Optional[str]]] = None,
        chunk_indices: Optional[List[Optional[int]]] = None,
        request_id: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> List[List[float]]:
        """
        Generate embeddings for multiple texts in a single API call.

        This method batches multiple embedding requests into one HTTP call,
        significantly reducing network overhead and improving throughput.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors, one per input text, in the same order.

        Behavior:
            -   If no model is available, returns dummy vectors.
            -   If batch API call fails, automatically falls back to sequential
                individual calls for robustness.
            -   Validates all returned embeddings.
        """
        if not texts:
            return []

        if self._use_dummy:
            if self._require_live:
                raise RuntimeError("LM Studio embeddings required but service is in dummy mode.")
            return [self._dummy_vector() for _ in texts]

        payload = {"model": self._model_name, "input": texts}
        if ttl is not None:
            payload["ttl"] = ttl
        request_id = request_id or f"embed-batch-{uuid.uuid4().hex[:12]}"
        sources = sources or []
        chunk_indices = chunk_indices or []

        for root in self._candidate_roots:
            url = f"{root}/v1/embeddings"
            try:
                started = time.perf_counter()
                emit_structured_log(
                    logger,
                    component="lmstudio_embedding_client",
                    request_id=request_id,
                    operation="embedding_batch_request_start",
                    model_name=self._model_name or "",
                    endpoint=url,
                    batch_size=len(texts),
                    payload_keys=sorted(payload.keys()),
                    payload_summary={
                        "model": payload.get("model"),
                        "input_count": len(texts),
                    },
                    ttl=payload.get("ttl"),
                    first_source=sources[0] if sources else None,
                    first_chunk_index=chunk_indices[0] if chunk_indices else None,
                )
                resp = self._post_json(url, payload, timeout=60)  # Max 1 minute for batch
                data = self._to_json(resp)

                # Extract all embeddings from batch response
                if "data" not in data:
                    raise ValueError("Batch embedding response missing 'data' field")

                # Sort by index to ensure correct order
                embeddings_data = sorted(data["data"], key=lambda x: x.get("index", 0))

                results = []
                for item in embeddings_data:
                    if not isinstance(item, dict) or "embedding" not in item:
                        raise ValueError(f"Invalid embedding item in batch response: {item}")
                    raw_vector = item["embedding"]
                    vector = self._normalize_and_validate_vector(raw_vector)
                    results.append(vector)

                if len(results) != len(texts):
                    raise ValueError(
                        f"Batch embedding count mismatch: expected {len(texts)}, got {len(results)}"
                    )

                self._api_root = root
                self._embed_url = url
                emit_structured_log(
                    logger,
                    component="lmstudio_embedding_client",
                    request_id=request_id,
                    operation="embedding_batch_request_end",
                    model_name=self._model_name or "",
                    duration_ms=(time.perf_counter() - started) * 1000.0,
                    endpoint=url,
                    status_code=resp.status_code,
                    batch_size=len(results),
                    embedding_dim=len(results[0]) if results else 0,
                )
                return results

            except requests.exceptions.RequestException as exc:
                logger.warning("Batch embedding HTTP error (%s); attempting next endpoint: %s", root, exc)
                emit_structured_log(
                    logger,
                    component="lmstudio_embedding_client",
                    request_id=request_id,
                    operation="embedding_batch_request_error",
                    model_name=self._model_name or "",
                    endpoint=url,
                    error=str(exc),
                )
                continue
            except (ValueError, TypeError) as exc:
                logger.warning("Batch embedding failed (%s); falling back to sequential generation", exc)
                emit_structured_log(
                    logger,
                    component="lmstudio_embedding_client",
                    request_id=request_id,
                    operation="embedding_batch_fallback_sequential",
                    model_name=self._model_name or "",
                    endpoint=url,
                    error=str(exc),
                )
                # Fallback to sequential generation for robustness
                return [
                    self.generate(
                        text,
                        source=(sources[idx] if idx < len(sources) else None),
                        chunk_index=(chunk_indices[idx] if idx < len(chunk_indices) else None),
                        request_id=request_id,
                        ttl=ttl,
                    )
                    for idx, text in enumerate(texts)
                ]

        # All endpoints failed, fall back to sequential
        logger.warning("All batch embedding endpoints failed; falling back to sequential generation")
        emit_structured_log(
            logger,
            component="lmstudio_embedding_client",
            request_id=request_id,
            operation="embedding_batch_all_endpoints_failed",
            model_name=self._model_name or "",
            batch_size=len(texts),
        )
        return [
            self.generate(
                text,
                source=(sources[idx] if idx < len(sources) else None),
                chunk_index=(chunk_indices[idx] if idx < len(chunk_indices) else None),
                request_id=request_id,
                ttl=ttl,
            )
            for idx, text in enumerate(texts)
        ]

    # ------------- Internals -------------

    def _post_json(self, url: str, payload: Dict[str, Any], timeout: float) -> Response:
        """
        POST JSON with basic error handling. Raises for HTTP status errors.
        """
        resp = self._session.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp

    def _to_json(self, response: Response) -> Dict[str, Any]:
        """
        Convert a Response to JSON dict. Raises ValueError if not a dict.
        """
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError(f"Embeddings API returned non-dict JSON: {type(data)}")
        return data

    def _extract_vector(self, data: Dict[str, Any]) -> Sequence[float] | List[float]:
        """
        Extract the embedding vector from an OpenAI/LM-Studio-like JSON structure.

        Supported shapes:
            - {"data": [{"embedding": [ ... floats ... ]}, ...], ...}
            - {"embedding": [ ... floats ... ], ...}

        Returns:
            The raw sequence of floats (not yet validated).
        """
        # Common OpenAI-like schema: pick the first embedding
        if "data" in data and isinstance(data["data"], list) and data["data"]:
            item = data["data"][0]
            if isinstance(item, dict) and "embedding" in item:
                return item["embedding"]

        # Sometimes the server returns the vector directly at top-level
        if "embedding" in data:
            return data["embedding"]

        raise ValueError(f"Unrecognized embedding schema: keys={list(data.keys())}")

    def _normalize_and_validate_vector(self, vector: Any) -> List[float]:
        """
        Ensure a flat list of floats with exact dimensionality, no None/NaN/Inf.
        """
        if vector is None:
            raise ValueError("Embedding vector is None.")

        # Accept numpy arrays without importing numpy as a hard dependency
        if hasattr(vector, "tolist") and callable(getattr(vector, "tolist")):
            vector = vector.tolist()

        if not isinstance(vector, Sequence) or isinstance(vector, (str, bytes)):
            raise TypeError(f"Embedding vector must be a sequence of floats, got {type(vector)}")

        if len(vector) != self._expected_dim:
            raise ValueError(
                f"Embedding dimension mismatch: expected {self._expected_dim}, got {len(vector)}"
            )

        out: List[float] = []
        for idx, val in enumerate(vector):
            if val is None:
                raise ValueError(f"Embedding contains None at index {idx}")
            try:
                f = float(val)
            except (TypeError, ValueError) as exc:
                raise TypeError(f"Embedding contains non-numeric at index {idx}: {val!r}") from exc
            if not math.isfinite(f):
                raise ValueError(f"Embedding contains non-finite at index {idx}: {f!r}")
            out.append(f)

        return out

    def _dummy_vector(self) -> List[float]:
        """
        Build a zero vector for fallback scenarios. Size is EMBEDDING_DIM.
        """
        return [0.0] * self._expected_dim
