from src.providers.adapters.base import ProviderAdapterBase
from src.providers.anythingllm.client import AnythingLLMChat
from src.rag.interfaces.embedding_interface import EmbeddingInterface


class AnythingLLMEmbeddings(EmbeddingInterface):
    def generate(self, text: str) -> list[float]:
        raise NotImplementedError("AnythingLLM embeddings not implemented.")


class AnythingLLMAdapter(ProviderAdapterBase):
    def __init__(self, config) -> None:
        _ = config
        super().__init__(AnythingLLMEmbeddings(), AnythingLLMChat())
