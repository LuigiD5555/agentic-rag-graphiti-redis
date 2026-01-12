from src.workflows.query.apps import AppConfig
from src.backends.llm.registry import register_provider


class LiteLLMGatewayAppConfig(AppConfig):
    def __init__(self) -> None:
        super().__init__(name="src.backends.llm.litellm_gateway", label="litellm_gateway")

    def ready(self) -> None:
        from src.backends.llm.litellm_gateway.adapter import LiteLLMGatewayAdapter

        register_provider("litellm", lambda cfg: LiteLLMGatewayAdapter(cfg))
