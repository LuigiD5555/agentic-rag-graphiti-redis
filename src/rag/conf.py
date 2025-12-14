"""
Settings loader similar in spirit to Django's LazySettings.

It builds a single ConfigLogic instance from src.settings (ALL-CAPS only),
applying env/.env overrides via ConfigFactory. Call get_settings(**overrides)
to get a copy with updates, or use the module-level `settings` singleton.
"""
from importlib import import_module
from typing import Any

from src.rag.engine import ConfigFactory


_settings_module = import_module("src.settings")
_factory = ConfigFactory(_settings_module.__dict__)

# Singleton settings object (canonical)
settings = _factory()


def Config(**overrides: Any):
    """
    Return the canonical settings object, optionally cloning with overrides.
    """
    if overrides:
        return settings.copy(update=overrides)
    return settings


def get_settings(**overrides: Any):
    return Config(**overrides)


__all__ = ["settings", "Config", "get_settings"]
