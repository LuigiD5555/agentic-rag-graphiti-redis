from abc import ABC, abstractmethod
from src.workflows.query.interfaces.embedding_interface import EmbeddingInterface
from src.workflows.query.interfaces.chat_interface import ChatInterface


class ProviderAdapterInterface(ABC):
    """
    Provider adapter exposes unified EmbeddingInterface and ChatInterface
    regardless of the underlying provider (LM Studio, OpenAI, etc.).
    """

    @abstractmethod
    def embeddings(self) -> EmbeddingInterface:
        """Return the embedding service."""
        raise NotImplementedError

    @abstractmethod
    def chat(self) -> ChatInterface:
        """Return the chat/LLM service."""
        raise NotImplementedError
