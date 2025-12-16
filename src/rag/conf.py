"""Settings loader - provides global config instance."""
from src.rag.engine import config

# Singleton settings object
settings = config


def Config(**overrides):
    """Return the canonical settings object.

    Note: Pydantic settings are immutable by default.
    For overrides, create a new instance with model_copy(update=overrides).
    """
    if overrides:
        return settings.model_copy(update=overrides)
    return settings


def get_settings(**overrides):
    """Alias for Config()."""
    return Config(**overrides)


__all__ = ["settings", "Config", "get_settings"]