from __future__ import annotations

from src.rag.apps import AppConfig
from src.providers.registry import register_provider


class LiteLLMGatewayAppConfig(AppConfig):
    def __init__(self) -> None:
        super().__init__(name="src.providers.litellm_gateway", label="litellm_gateway")

    def ready(self) -> None:
        from src.providers.litellm_gateway.adapter import LiteLLMGatewayAdapter

        register_provider("litellm", lambda cfg: LiteLLMGatewayAdapter(cfg))
