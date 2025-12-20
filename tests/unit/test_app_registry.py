from src.providers.registry import list_providers, reset_provider_registry
from src.providers.app_registry import ensure_apps_loaded, reset_app_registry
from src.providers.builtins import _reset_for_tests as reset_builtin_providers
from src.rag.conf import Config


def test_installed_apps_populate_provider_registry():
    reset_app_registry()
    reset_provider_registry()
    reset_builtin_providers()

    cfg = Config().copy(
        update={
            "INSTALLED_APPS": [
                "src.providers.lmstudio.apps.LMStudioProviderAppConfig",
                "src.providers.openai.apps.OpenAIProviderAppConfig",
                "src.providers.litellm_gateway.apps.LiteLLMGatewayAppConfig",
            ]
        }
    )
    ensure_apps_loaded(cfg)

    providers = set(list_providers())
    assert "ollama" in providers
    assert "lmstudio" in providers
    assert "openai" in providers
    assert "litellm" in providers
