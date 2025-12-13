from __future__ import annotations

from src.rag.apps import AppConfig
from src.providers.registry import register_provider


class LMStudioProviderAppConfig(AppConfig):
    def __init__(self) -> None:
        super().__init__(name="src.providers.lmstudio", label="provider_lmstudio")

    def ready(self) -> None:
        from src.providers.adapters.lmstudio_adapter import LMStudioAdapter

        register_provider("lmstudio", lambda cfg: LMStudioAdapter(cfg))

