"""
Module with services that generate embeddings using an LM Studio-compatible endpoint.

Key behaviors:
-   Object-oriented design.
-   No custom exceptions; only built-in and requests' exceptions are used.
-   Strong validation: ensures the returned embedding is a flat list[float],
    with exact dimensionality (from Config), and only finite values.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Sequence, Optional
import requests
from requests import Response
from src import logger


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
            -   (optional) EMBEDDING_MODEL: str -> explicit model name (if you prefer to override).

        Model selection:
            -   If EMBEDDING_MODEL is not set, uses model_manager.get_first_embedding_model().
            -   If no model is available, the service falls back to a zero vector (dummy)
                and logs a warning.
        """
        api_root = str(config.LM_EMBED_URL).rstrip("/")
        if api_root.endswith("/v1/embeddings"):
            api_root = api_root.rsplit("/v1/embeddings", 1)[0]
        self._embed_url: str = f"{api_root}/v1/embeddings"

        # Expected embedding dimension for validation and dummy fallback
        self._expected_dim: int = int(getattr(config, "EMBEDDING_DIM", 768))

        # Model selection (explicit override or first available)
        explicit_model: Optional[str] = getattr(config, "EMBEDDING_MODEL", None)
        if explicit_model:
            self._model_name = explicit_model
        else:
            self._model_name = model_manager.get_first_embedding_model()

        self._use_dummy: bool = not bool(self._model_name)
        if self._use_dummy:
            logger.warning(
                "No embedding model found. Using dummy embeddings of size %d.", self._expected_dim
            )
        else:
            logger.info("Selected embedding model: %s", self._model_name)

        # Optional: a requests.Session could be used for connection pooling
        self._session = requests.Session()

    # ------------- Public API -------------

    def generate(self, text: str) -> List[float]:
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
            return self._dummy_vector()

        payload = {"model": self._model_name, "input": text}
        try:
            resp = self._post_json(self._embed_url, payload, timeout=15)
            data = self._to_json(resp)
            raw_vector = self._extract_vector(data)
            vector = self._normalize_and_validate_vector(raw_vector)
            return vector
        except requests.exceptions.RequestException as exc:
            logger.error("Embedding HTTP error; returning dummy vector: %s", exc)
            return self._dummy_vector()
        except (ValueError, TypeError) as exc:
            # Schema/dimensionality/contents invalid — surface clearly or choose to fallback
            logger.error("Invalid embedding response; returning dummy vector: %s", exc)
            return self._dummy_vector()

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
