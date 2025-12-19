from typing import Optional

from src.providers.factory import ProviderFactory
from src.rag.conf import Config
from src.rag.interfaces.embedding_interface import EmbeddingInterface


def get_embedding_service(
    config: Config,
    provider: Optional[ProviderFactory] = None,
) -> EmbeddingInterface:
    """
    Return the embedding service from the configured provider (LM Studio).

    The service automatically detects model dimensions from the first available
    embedding model in LM Studio.
    """
    provider = provider or ProviderFactory(config)
    return provider.embeddings()
