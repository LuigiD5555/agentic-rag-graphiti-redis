from src.backends.llm.adapters.base import ProviderAdapterBase
from src.backends.llm.huggingface.client import HuggingFaceChat
from src.workflows.query.interfaces.embedding_interface import EmbeddingInterface


class HuggingFaceEmbeddings(EmbeddingInterface):
    def generate(self, text: str) -> list[float]:
        raise NotImplementedError("HuggingFace embeddings not implemented.")


class HuggingFaceAdapter(ProviderAdapterBase):
    def __init__(self, config) -> None:
        _ = config
        super().__init__(HuggingFaceEmbeddings(), HuggingFaceChat())
