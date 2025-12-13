from __future__ import annotations

from src.providers.adapters.base import ProviderAdapterBase
from src.providers.ollama.client import OllamaChat
from src.rag.interfaces.embedding_interface import EmbeddingInterface


class OllamaEmbeddings(EmbeddingInterface):
    def generate(self, text: str) -> list[float]:
        raise NotImplementedError("Ollama embeddings not implemented.")


class OllamaAdapter(ProviderAdapterBase):
    def __init__(self, config) -> None:
        _ = config
        super().__init__(OllamaEmbeddings(), OllamaChat())

