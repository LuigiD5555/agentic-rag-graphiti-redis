from src.providers.registry import register_provider

_builtin_registered = False


def ensure_builtin_providers_loaded() -> None:
    """
    Register providers that are always available as part of the core `rag` app.

    Per project convention: only `ollama` is treated as native/built-in.
    """
    global _builtin_registered
    if _builtin_registered:
        return

    from src.providers.ollama.adapter import OllamaAdapter

    register_provider("ollama", lambda cfg: OllamaAdapter(cfg))
    _builtin_registered = True


def _reset_for_tests() -> None:  # pragma: no cover
    global _builtin_registered
    _builtin_registered = False
