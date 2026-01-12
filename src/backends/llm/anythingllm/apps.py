from src.workflows.query.apps import AppConfig
from src.backends.llm.registry import register_provider


class AnythingLLMProviderAppConfig(AppConfig):
    def __init__(self) -> None:
        super().__init__(name="src.backends.llm.anythingllm", label="provider_anythingllm")

    def ready(self) -> None:
        from src.backends.llm.anythingllm.adapter import AnythingLLMAdapter

        register_provider("anythingllm", lambda cfg: AnythingLLMAdapter(cfg))
