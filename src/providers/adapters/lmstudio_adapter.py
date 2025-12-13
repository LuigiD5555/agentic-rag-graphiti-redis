from src.providers.adapters.base import ProviderAdapterBase
from src.rag.interfaces.embedding_interface import EmbeddingInterface
from src.rag.interfaces.chat_interface import ChatInterface
from src.providers.lmstudio.model_manager import ModelManager
from src.providers.lmstudio.embeddings import EmbeddingService
from src.providers.lmstudio.client import LLMService
from src.settings import Config


class LMStudioAdapter(ProviderAdapterBase):
    """
    Adapter for LM Studio provider (local HTTP server). Reuses existing client modules.
    """

    def __init__(self, config: Config):
        mm = ModelManager(
            config.LMSTUDIO_API_ROOTS,
            require_live=config.LMSTUDIO_REQUIRE_SERVER,
        )
        embedding: EmbeddingInterface = EmbeddingService(config, mm)
        chat: ChatInterface = LLMService(config, mm)
        super().__init__(embedding, chat)
