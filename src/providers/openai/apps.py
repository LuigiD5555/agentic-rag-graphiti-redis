from __future__ import annotations

from src.rag.apps import AppConfig
from src.providers.registry import register_provider


class OpenAIProviderAppConfig(AppConfig):
    def __init__(self) -> None:
        super().__init__(name="src.providers.openai", label="provider_openai")

    def ready(self) -> None:
        from src.providers.adapters.openai_adapter import OpenAIAdapter

        register_provider("openai", lambda cfg: OpenAIAdapter(cfg))

