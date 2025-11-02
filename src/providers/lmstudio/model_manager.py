"""Module that manages language models and embeddings models."""
from typing import Dict, Iterable, List, Sequence
import requests
from src import logger


class ModelManager:
    """
    Centralized model manager for LM Studio.
    Fetches available models once and categorizes them.
    """

    def __init__(self, api_roots: Sequence[str] | str, require_live: bool = False):
        """
        Initialize ModelManager with LM Studio API root.
        """
        if isinstance(api_roots, str):
            candidates: Iterable[str] = [api_roots]
        else:
            candidates = api_roots

        self.api_roots = [candidate.rstrip("/") for candidate in candidates if candidate]
        self.api_root: str | None = None
        self.language_models: List[Dict] = []
        self.embedding_models: List[Dict] = []
        self.failed_roots: List[str] = []
        self.require_live = require_live

        self._fetch_models()

    def _fetch_models(self):
        """Fetch and categorize models from LM Studio."""
        for root in self.api_roots:
            models_url = f"{root}/v1/models"
            try:
                response = requests.get(models_url, timeout=5)
                response.raise_for_status()
                models = response.json().get("data", [])

                self.embedding_models = [m["id"] for m in models if "embed" in m["id"].lower()]
                self.language_models = [m["id"] for m in models if "embed" not in m["id"].lower()]

                self.api_root = root
                logger.info("LM Studio models fetched from %s", root)
                logger.info("Available embedding models: %s", self.embedding_models)
                logger.info("Available language models: %s", self.language_models)
                return
            except requests.exceptions.RequestException as exc:
                logger.error("Failed to fetch models from LM Studio (%s): %s", models_url, exc)
                self.failed_roots.append(root)

        # If every root failed, keep empty lists and default to first candidate for downstream URLs.
        self.embedding_models = []
        self.language_models = []
        if self.api_roots:
            self.api_root = self.api_roots[0]
        if self.require_live:
            raise RuntimeError(
                "LM Studio model list could not be fetched from any configured endpoint "
                f"(tried: {self.api_roots})."
            )

    def get_first_embedding_model(self):
        """Return the first embedding model or None."""
        return self.embedding_models[0] if self.embedding_models else None

    def get_first_language_model(self):
        """Return the first non-embedding model or None."""
        return self.language_models[0] if self.language_models else None
