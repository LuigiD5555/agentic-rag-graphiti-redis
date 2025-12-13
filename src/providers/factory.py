from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.settings import Config
from src.rag.interfaces.embedding_interface import EmbeddingInterface
from src.rag.interfaces.chat_interface import ChatInterface
from src.providers.adapters.lmstudio_adapter import LMStudioAdapter
from src.providers.adapters.openai_adapter import OpenAIAdapter
from src.rag.interfaces.provider_adapter_interface import ProviderAdapterInterface


@dataclass
class ProviderFactory:
    """
    Factory for provider adapters (embeddings + LLM) selected from Config.

    Env knob (optional): PROVIDER = lmstudio | openai
    Defaults to lmstudio.
    """

    config: Config
    _adapter: Optional[ProviderAdapterInterface] = None

    def _select_adapter(self) -> ProviderAdapterInterface:
        if self._adapter is None:
            provider = (getattr(self.config, "PROVIDER", None) or "lmstudio").lower()
            if provider == "openai":
                self._adapter = OpenAIAdapter(self.config)
            else:
                self._adapter = LMStudioAdapter(self.config)
        return self._adapter

    def embeddings(self) -> EmbeddingInterface:
        return self._select_adapter().embeddings()

    def chat(self) -> ChatInterface:
        return self._select_adapter().chat()
