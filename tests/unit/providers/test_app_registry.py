from src.backends.llm.registry import list_providers, reset_provider_registry
from src.backends.llm.app_registry import ensure_apps_loaded, reset_app_registry
from src.backends.llm.builtins import _reset_for_tests as reset_builtin_providers
from src.workflows.query.conf import Config
from pytest_readable import readable



@readable(
    intent="Verify installed apps populate provider registry.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the installed apps populate provider registry behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_installed_apps_populate_provider_registry():
    reset_app_registry()
    reset_provider_registry()
    reset_builtin_providers()

    cfg = Config().model_copy(
        update={
            "INSTALLED_APPS": [
                "src.backends.llm.lmstudio.apps.LMStudioProviderAppConfig",
                "src.backends.llm.openai.apps.OpenAIProviderAppConfig",
                "src.backends.llm.litellm_gateway.apps.LiteLLMGatewayAppConfig",
            ]
        }
    )
    ensure_apps_loaded(cfg)

    providers = set(list_providers())
    assert "lmstudio" in providers
    assert "openai" in providers
    assert "litellm" in providers
