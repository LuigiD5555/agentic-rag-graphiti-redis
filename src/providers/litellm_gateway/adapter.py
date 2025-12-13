from __future__ import annotations

from src.rag.interfaces.provider_adapter_interface import ProviderAdapterInterface
from src.providers.registry import get_provider_factory


class LiteLLMGatewayAdapter(ProviderAdapterInterface):
    """
    Lightweight gateway that *simulates* LiteLLM behavior without depending on it.

    It delegates to another registered provider selected via:
        - Config.LITELLM_TARGET_PROVIDER (default: "lmstudio")

    This provides the integration wiring for external apps/providers.
    """

    def __init__(self, config) -> None:
        self._config = config
        target = (getattr(config, "LITELLM_TARGET_PROVIDER", None) or "lmstudio").strip().lower()
        if target == "litellm":
            raise ValueError("LITELLM_TARGET_PROVIDER cannot be 'litellm' (would recurse)")
        self._delegate = get_provider_factory(target)(config)

    def embeddings(self):
        return self._delegate.embeddings()

    def chat(self):
        return self._delegate.chat()

