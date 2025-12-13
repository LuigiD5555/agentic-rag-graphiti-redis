from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from src.settings import Config
from src.rag.interfaces.embedding_interface import EmbeddingInterface
from src.rag.interfaces.chat_interface import ChatInterface
from src.rag.interfaces.provider_adapter_interface import ProviderAdapterInterface
from src.rag.registry import ensure_apps_loaded
from src.providers.registry import get_provider_factory


@dataclass
class ProviderFactory:
    """
    Factory for provider adapters (embeddings + LLM) selected from Config.

    Env knob (optional): PROVIDER = lmstudio | openai | huggingface | anythingllm | litellm | ollama
    Defaults to lmstudio.

    Notes:
    - Providers are registered by installed apps (Config.INSTALLED_APPS).
    - The only built-in provider is `ollama` (registered by the core rag app).
    """

    config: Config
    _adapter: Optional[ProviderAdapterInterface] = None

    def _select_adapter(self) -> ProviderAdapterInterface:
        if self._adapter is None:
            ensure_apps_loaded(self.config)
            provider = (getattr(self.config, "PROVIDER", None) or "lmstudio").lower()
            factory = get_provider_factory(provider)
            self._adapter = factory(self.config)
        return self._adapter

    def embeddings(self) -> EmbeddingInterface:
        return self._select_adapter().embeddings()

    def chat(self) -> ChatInterface:
        return self._select_adapter().chat()
