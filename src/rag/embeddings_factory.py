from typing import Optional

from src import logger
from src.providers.factory import ProviderFactory
from src.rag.conf import Config
from src.rag.interfaces.embedding_interface import EmbeddingInterface


def get_embedding_service(
    config: Config,
    provider: Optional[ProviderFactory] = None,
) -> EmbeddingInterface:
    """
    Return the embedding service specified by the configuration.

    Defaults to LM Studio, but can be switched to GPU-backed local embeddings.
    """
    backend = (getattr(config, "EMBEDDING_BACKEND", "lmstudio") or "lmstudio").strip().lower()
    if backend == "local_gpu":
        # Keep torch/sentence-transformers optional unless explicitly enabled.
        try:
            from src.utils.local_gpu.factory import build_local_gpu_embedding_service

            return build_local_gpu_embedding_service(config)
        except ModuleNotFoundError as exc:
            missing = getattr(exc, "name", "") or str(exc)
            # Most common missing deps: torch, sentence_transformers
            if missing in {"torch", "sentence_transformers"} or "torch" in missing:
                provider = provider or ProviderFactory(config)
                # Avoid hard-crashing if user enabled local_gpu without installing deps.
                logger.warning(
                    "EMBEDDING_BACKEND=local_gpu requested but dependency '%s' is missing; "
                    "falling back to provider embeddings. Install optional deps with "
                    "`pip install -r requirements.txt`.",
                    missing,
                )
                return provider.embeddings()
            raise

    provider = provider or ProviderFactory(config)
    return provider.embeddings()
