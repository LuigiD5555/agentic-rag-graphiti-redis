from typing import Optional, Any

from src.backends.llm.factory import ProviderFactory
from src.workflows.query.interfaces.embedding_interface import EmbeddingInterface


class _ConfigOverride:
    """Lightweight config proxy that overrides selected attributes."""

    def __init__(self, base: Any, **overrides: Any) -> None:
        self._base = base
        for key, value in overrides.items():
            setattr(self, key, value)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)


def _pick_context_model(config: Any, context: str) -> str:
    base = (getattr(config, "EMBEDDING_MODEL", "") or "").strip()
    legacy = (getattr(config, "LMSTUDIO_EMBED_MODEL", "") or "").strip()
    if context == "ingest":
        return (
            (getattr(config, "EMBEDDING_MODEL_INGEST", "") or "").strip()
            or base
            or legacy
        )
    if context == "query":
        return (
            (getattr(config, "EMBEDDING_MODEL_QUERY", "") or "").strip()
            or base
            or legacy
        )
    raise ValueError(f"Unknown embedding context: {context}")


def get_embedding_service(
    config: Any,
    provider: Optional[ProviderFactory] = None,
    context: str = "query",
) -> EmbeddingInterface:
    """
    Return the embedding service from the configured provider (LM Studio).
    """
    selected_model = _pick_context_model(config, context)
    current_model = (getattr(config, "EMBEDDING_MODEL", "") or "").strip()

    if selected_model and selected_model != current_model:
        config = _ConfigOverride(config, EMBEDDING_MODEL=selected_model)
        provider = ProviderFactory(config)

    provider = provider or ProviderFactory(config)
    return provider.embeddings()
