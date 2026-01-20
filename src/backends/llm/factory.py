from dataclasses import dataclass
from typing import Optional, Any

from src.workflows.query.interfaces.embedding_interface import EmbeddingInterface
from src.workflows.query.interfaces.chat_interface import ChatInterface
from src.workflows.query.interfaces.provider_adapter_interface import ProviderAdapterInterface
from src.backends.llm.app_registry import ensure_apps_loaded
from src.backends.llm.registry import get_provider_factory


@dataclass
class ProviderFactory:
    """
    Factory for provider adapters (embeddings + LLM) selected from config.

    Env knob (optional): PROVIDER = lmstudio | openai | huggingface | anythingllm | litellm | ollama
    Defaults to lmstudio.

    Notes:
    - Providers are registered by installed apps (INSTALLED_APPS).
    - The only built-in provider is `ollama` (registered by the core rag app).
    """

    config: Any
    _adapter: Optional[ProviderAdapterInterface] = None

    def _select_adapter(self) -> ProviderAdapterInterface:
        if self._adapter is not None:
            return self._adapter
            
        ensure_apps_loaded(self.config)
        provider = self._get_provider_config()
        provider = provider or "lmstudio"
        factory = get_provider_factory(provider)
        self._adapter = factory(self.config)
        return self._adapter
        
    def _get_provider_config(self) -> str:
        """Get provider configuration with fallback logic."""
        provider = (getattr(self.config, "PROVIDER", None) or "").strip().lower()
        if provider:
            return provider
            
        providers = getattr(self.config, "PROVIDERS", None) or {}
        default_cfg = providers.get("default") if isinstance(providers, dict) else None
        if isinstance(default_cfg, dict):
            return (default_cfg.get("ENGINE") or default_cfg.get("BACKEND") or "").strip().lower()
            
        return ""

    def embeddings(self) -> EmbeddingInterface:
        return self._select_adapter().embeddings()

    def chat(self) -> ChatInterface:
        return self._select_adapter().chat()
