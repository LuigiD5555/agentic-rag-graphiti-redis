"""Module that manages language models and embeddings models."""
from typing import Dict, Iterable, List, Sequence, Optional
import requests
from src import logger


# Known embedding model dimensions (pattern matching)
EMBEDDING_MODEL_DIMENSIONS = {
    # 768-dimensional models
    "nomic-embed-text-v2": 768,
    "nomic-embed-text-v1.5": 768,
    "all-mpnet-base": 768,
    "all-roberta-large": 768,
    "bge-base": 768,
    "bge-large": 768,
    "e5-base": 768,
    "e5-large": 768,
    "gte-base": 768,
    "gte-large": 768,
    "instructor-base": 768,
    "instructor-large": 768,

    # 384-dimensional models
    "all-minilm-l6": 384,
    "all-minilm-l12": 384,
    "paraphrase-multilingual-minilm": 384,
    "bge-small": 384,
    "bge-micro": 384,
    "e5-small": 384,
    "gte-small": 384,

    # 1024-dimensional models
    "bge-m3": 1024,
    "e5-mistral": 1024,

    # 1536-dimensional models (OpenAI-style)
    "text-embedding-ada": 1536,
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
}


def detect_model_dimensions(model_name: str) -> Optional[int]:
    """Detect embedding dimensions from model name using pattern matching.

    Args:
        model_name: The model identifier (e.g., 'text-embedding-nomic-embed-text-v2-moe')

    Returns:
        Detected dimension size or None if unknown
    """
    if not model_name:
        return None

    model_lower = model_name.lower()

    # Check for exact pattern matches
    for pattern, dim in EMBEDDING_MODEL_DIMENSIONS.items():
        if pattern in model_lower:
            return dim

    return None


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

                # Filter out reranker models from embeddings (they have "rerank" in the name)
                self.embedding_models = [
                    m["id"] for m in models
                    if "embed" in m["id"].lower() and "rerank" not in m["id"].lower()
                ]
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

    def get_model_dimensions(self, model_name: str) -> Optional[int]:
        """Get the dimension size for a given embedding model.

        Args:
            model_name: The model identifier

        Returns:
            Dimension size or None if unknown
        """
        return detect_model_dimensions(model_name)
