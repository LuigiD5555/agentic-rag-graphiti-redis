from __future__ import annotations

from src.rag.apps import AppConfig
from src.providers.registry import register_provider


class AnythingLLMProviderAppConfig(AppConfig):
    def __init__(self) -> None:
        super().__init__(name="src.providers.anythingllm", label="provider_anythingllm")

    def ready(self) -> None:
        from src.providers.anythingllm.adapter import AnythingLLMAdapter

        register_provider("anythingllm", lambda cfg: AnythingLLMAdapter(cfg))

