from dataclasses import dataclass
from src.interfaces.provider_adapter_interface import ProviderAdapterInterface
from src.interfaces.embedding_interface import EmbeddingInterface
from src.interfaces.chat_interface import ChatInterface


@dataclass
class ProviderAdapterBase(ProviderAdapterInterface):
    """
    Concrete helper that stores embedding/chat services.
    Not abstract: it satisfies the interface directly.
    """

    _embedding: EmbeddingInterface
    _chat: ChatInterface

    def embeddings(self) -> EmbeddingInterface:
        return self._embedding

    def chat(self) -> ChatInterface:
        return self._chat
