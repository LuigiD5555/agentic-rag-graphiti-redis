"""
Module with services that generate embeddings using an LM Studio-compatible endpoint.

Key behaviors:
-   Object-oriented design.
-   No custom exceptions; only built-in and requests' exceptions are used.
-   Strong validation: ensures the returned embedding is a flat list[float],
    with exact dimensionality (from Config), and only finite values.
"""

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

        # Model selection (explicit override or first available)
        explicit_model: Optional[str] = getattr(config, "EMBEDDING_MODEL", None)
        if explicit_model:
            self._model_name = explicit_model
        else:
            self._model_name = model_manager.get_first_embedding_model()

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
            if self._require_live:
                raise RuntimeError("LM Studio embeddings required but service is in dummy mode.")
            return self._dummy_vector()

        payload = {"model": self._model_name, "input": text}
        for root in self._candidate_roots:
            url = f"{root}/v1/embeddings"
            try:
                resp = self._post_json(url, payload, timeout=15)
                data = self._to_json(resp)
                raw_vector = self._extract_vector(data)
                vector = self._normalize_and_validate_vector(raw_vector)
                self._api_root = root
                self._embed_url = url
                return vector
            except requests.exceptions.RequestException as exc:
                logger.error("Embedding HTTP error (%s); attempting next endpoint: %s", root, exc)
                continue
            except (ValueError, TypeError) as exc:
                logger.error("Invalid embedding response; returning dummy vector: %s", exc)
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

    def generate_batch(self, texts: List[str]) -> List[List[float]]:
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

        for root in self._candidate_roots:
            url = f"{root}/v1/embeddings"
            try:
                resp = self._post_json(url, payload, timeout=30)  # Longer timeout for batch
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
                return results

            except requests.exceptions.RequestException as exc:
                logger.warning("Batch embedding HTTP error (%s); attempting next endpoint: %s", root, exc)
                continue
            except (ValueError, TypeError) as exc:
                logger.warning("Batch embedding failed (%s); falling back to sequential generation", exc)
                # Fallback to sequential generation for robustness
                return [self.generate(text) for text in texts]

        # All endpoints failed, fall back to sequential
        logger.warning("All batch embedding endpoints failed; falling back to sequential generation")
        return [self.generate(text) for text in texts]

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
