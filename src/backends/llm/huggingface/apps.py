from src.workflows.query.apps import AppConfig
from src.backends.llm.registry import register_provider


class HuggingFaceProviderAppConfig(AppConfig):
    def __init__(self) -> None:
        super().__init__(name="src.backends.llm.huggingface", label="provider_huggingface")

    def ready(self) -> None:
        from src.backends.llm.huggingface.adapter import HuggingFaceAdapter

        register_provider("huggingface", lambda cfg: HuggingFaceAdapter(cfg))
