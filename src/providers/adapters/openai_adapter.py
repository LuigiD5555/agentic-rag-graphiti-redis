from src.providers.adapters.base import ProviderAdapterBase
from src.rag.interfaces.embedding_interface import EmbeddingInterface
from src.rag.interfaces.chat_interface import ChatInterface
from src.rag.conf import Config


class OpenAIEmbeddings(EmbeddingInterface):
    """Placeholder: implement calls to OpenAI Embeddings API."""
    def __init__(self, config: Config):
        self._config = config

    def generate(self, text: str) -> list[float]:
        raise NotImplementedError("OpenAI embeddings not implemented.")


class OpenAIChat(ChatInterface):
    """Placeholder: implement calls to OpenAI ChatCompletions API."""
    def __init__(self, config: Config):
        self._config = config

    def complete(self, prompt: str, max_tokens: int = 256) -> str:
        raise NotImplementedError("OpenAI chat not implemented.")


class OpenAIAdapter(ProviderAdapterBase):
    """Adapter for OpenAI provider (web)."""
    def __init__(self, config: Config):
        super().__init__(OpenAIEmbeddings(config), OpenAIChat(config))
