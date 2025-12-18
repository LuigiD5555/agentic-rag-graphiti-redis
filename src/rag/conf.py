"""Settings loader - provides global config instance."""

import json
import os
from pathlib import Path
from typing import Any

from src import logger
from src.rag.engine import config

# Singleton settings object
settings = config


def _looks_sensitive_key(key: str) -> bool:
    upper = key.upper()
    return any(token in upper for token in ("PASSWORD", "SECRET", "TOKEN", "API_KEY", "KEY"))


def _sanitize_for_json(value: Any, key_hint: str | None = None) -> Any:
    if key_hint and _looks_sensitive_key(key_hint):
        return None

    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return [_sanitize_for_json(v) for v in value]
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if not isinstance(k, str):
                continue
            if _looks_sensitive_key(k):
                continue
            sanitized = _sanitize_for_json(v, key_hint=k)
            if sanitized is not None:
                out[k] = sanitized
        return out
    return str(value)


def sync_settings_json() -> None:
    """Persist the active settings (from .env) into data/settings.json.

    This is intentionally best-effort:
    - It skips sensitive keys (PASSWORD/SECRET/TOKEN/API_KEY/KEY).
    - It does not crash the app if writing fails.

    Disable with: SYNC_SETTINGS_JSON=0
    """
    if os.environ.get("SYNC_SETTINGS_JSON", "1").strip() in {"0", "false", "False", "no", "NO"}:
        return

    settings_path_raw = getattr(settings, "USER_SETTINGS_FILE", "data/settings.json")
    settings_path = Path(str(settings_path_raw))
    if not settings_path.is_absolute():
        settings_path = Path(os.getcwd()) / settings_path

    try:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return

    try:
        current = settings.model_dump()  # pydantic-settings already applied env/.env
    except Exception as exc:
        logger.debug("Failed to dump settings for sync: %s", exc)
        return

    sanitized = _sanitize_for_json(current)
    if not isinstance(sanitized, dict):
        return

    try:
        existing: dict[str, Any] = {}
        if settings_path.is_file():
            existing = json.loads(settings_path.read_text(encoding="utf-8")) or {}
        if not isinstance(existing, dict):
            existing = {}
    except Exception:
        existing = {}

    merged = {**existing, **sanitized}

    try:
        tmp_path = settings_path.with_suffix(settings_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(merged, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp_path.replace(settings_path)
    except Exception as exc:
        logger.debug("Failed to write settings.json sync: %s", exc)
        return


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


__all__ = ["settings", "Config", "get_settings", "sync_settings_json"]
