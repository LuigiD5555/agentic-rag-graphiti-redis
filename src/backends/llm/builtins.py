from src.backends.llm.registry import provider

_builtin_registered = False


def ensure_builtin_providers_loaded() -> None:
    """
    Register providers that are always available as part of the core `rag` app.

    Per project convention: only `ollama` is treated as native/built-in.
    """
    global _builtin_registered
    if _builtin_registered:
        return

    # Import built-in providers to trigger decorator registration
    from src.backends.llm.ollama import adapter  # noqa: F401
    
    _builtin_registered = True


def _reset_for_tests() -> None:  # pragma: no cover
    global _builtin_registered
    _builtin_registered = False


# Built-in provider registrations using decorator pattern
@provider("ollama")
def build_ollama_adapter(config):
    """
    Build an Ollama adapter.
    
    Args:
        config: Application configuration
        
    Returns:
        OllamaAdapter instance
    """
    from src.backends.llm.ollama.adapter import OllamaAdapter
    return OllamaAdapter(config)
