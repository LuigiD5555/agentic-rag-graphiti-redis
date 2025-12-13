from __future__ import annotations

from src.rag.apps import AppConfig
from src.providers.registry import register_provider


class HuggingFaceProviderAppConfig(AppConfig):
    def __init__(self) -> None:
        super().__init__(name="src.providers.huggingface", label="provider_huggingface")

    def ready(self) -> None:
        from src.providers.huggingface.adapter import HuggingFaceAdapter

        register_provider("huggingface", lambda cfg: HuggingFaceAdapter(cfg))

