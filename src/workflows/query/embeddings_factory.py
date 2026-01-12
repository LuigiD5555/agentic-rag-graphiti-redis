from typing import Optional, Any

from src.backends.llm.factory import ProviderFactory
from src.workflows.query.interfaces.embedding_interface import EmbeddingInterface


def get_embedding_service(
    config: Any,
    provider: Optional[ProviderFactory] = None,
) -> EmbeddingInterface:
    """
    Return the embedding service from the configured provider (LM Studio).

    The service automatically detects model dimensions from the first available
    embedding model in LM Studio.
    """
    provider = provider or ProviderFactory(config)
    return provider.embeddings()
