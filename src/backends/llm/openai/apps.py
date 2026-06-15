from src.workflows.query.apps import AppConfig
from src.backends.llm.registry import register_provider


class OpenAIProviderAppConfig(AppConfig):
    def __init__(self) -> None:
        super().__init__(name="src.backends.llm.openai", label="provider_openai")

    def ready(self) -> None:
        from src.backends.llm.adapters.openai_adapter import OpenAIAdapter

        register_provider("openai", lambda cfg: OpenAIAdapter(cfg))
