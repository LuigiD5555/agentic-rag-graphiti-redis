from src.providers.adapters.base import ProviderAdapterBase
from src.interfaces.embedding_interface import EmbeddingInterface
from src.interfaces.chat_interface import ChatInterface
from src.providers.lmstudio.model_manager import ModelManager
from src.providers.lmstudio.embeddings import EmbeddingService
from src.providers.lmstudio.client import LLMService
from src.config.settings import Config


class LMStudioAdapter(ProviderAdapterBase):
    """
    Adapter for LM Studio provider (local HTTP server). Reuses existing client modules.
    """

    def __init__(self, config: Config):
        api_root = config.LM_EMBED_URL.rstrip("/")
        if api_root.endswith("/v1/embeddings"):
            api_root = api_root.rsplit("/v1/embeddings", 1)[0]
        mm = ModelManager(api_root)
        embedding: EmbeddingInterface = EmbeddingService(config, mm)
        chat: ChatInterface = LLMService(config, mm)
        super().__init__(embedding, chat)
