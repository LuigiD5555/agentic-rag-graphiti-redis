"""Project settings access (Django-like).

This project intentionally separates:

- ``src/settings.py``: declarative defaults and registries (data-only).
- ``src.conf.settings``: the runtime settings object used by the application.

This mirrors Django's pattern:

- ``myproject/settings.py`` (module)
- ``from django.conf import settings`` (runtime object)

Use ``from src.conf import settings`` in runtime code.
"""

from typing import Any, Dict

from src.workflows.query.conf import Config, get_settings, settings, sync_settings_json


def as_dict() -> Dict[str, Any]:
    """
    Export the runtime settings as a plain dictionary.

    Returns:
        A dictionary representation of the runtime settings.
    """
    if hasattr(settings, "model_dump"):
        return settings.model_dump()  # type: ignore[no-any-return]
    return dict(getattr(settings, "__dict__", {}))


__all__ = [
    "Config",
    "settings",
    "get_settings",
    "sync_settings_json",
    "as_dict",
]
