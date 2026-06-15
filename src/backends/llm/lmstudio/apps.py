from src.workflows.query.apps import AppConfig
from src.backends.llm.registry import register_provider


class LMStudioProviderAppConfig(AppConfig):
    def __init__(self) -> None:
        super().__init__(name="src.backends.llm.lmstudio", label="provider_lmstudio")

    def ready(self) -> None:
        from src.backends.llm.adapters.lmstudio_adapter import LMStudioAdapter

        register_provider("lmstudio", lambda cfg: LMStudioAdapter(cfg))
