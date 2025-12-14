"""
Cache backends (Redis by default).
"""

from __future__ import annotations

from typing import Any, Mapping

from src.rag.interfaces.cache_interface import CacheServiceProtocol

from .redis_cache import CacheService as RedisCacheService

CacheService = RedisCacheService


def _cache_settings(config, alias: str) -> Mapping[str, Any]:
    caches = getattr(config, "CACHES", None) or {}
    if not isinstance(caches, dict):
        raise TypeError("Config.CACHES must be a dict mapping aliases to dict settings")
    if alias not in caches:
        available = ", ".join(sorted(caches.keys())) or "<none>"
        raise KeyError(f"Unknown CACHES alias '{alias}'. Available: {available}")
    cache_cfg = caches[alias]
    if not isinstance(cache_cfg, dict):
        raise TypeError(f"Config.CACHES['{alias}'] must be a dict of settings")
    return cache_cfg


def get_cache(config, alias: str = "default") -> CacheServiceProtocol:
    """
    Create the cache backend selected in settings.

    Django-like usage:
        CACHES = {"default": {"BACKEND": "redis", "LOCATION": "redis://host:port/0", "OPTIONS": {}}}
    """
    cache_cfg = _cache_settings(config, alias)
    backend = (cache_cfg.get("BACKEND") or cache_cfg.get("ENGINE") or "redis").lower()

    if backend == "redis":
        update: dict[str, Any] = {}
        for key, value in cache_cfg.items():
            if key in {"BACKEND", "ENGINE", "OPTIONS", "TIMEOUT", "KEY_PREFIX", "VERSION"}:
                continue
            if key == "HOST":
                update["REDIS_HOST"] = value
                continue
            if key == "PORT":
                update["REDIS_PORT"] = value
                continue
            if key == "LOCATION":
                loc = str(value or "").strip()
                if loc.startswith("redis://"):
                    try:
                        host_port = loc.split("://", 1)[1].split("/", 1)[0]
                        host, port = host_port.split(":", 1)
                        update["REDIS_HOST"] = host
                        update["REDIS_PORT"] = int(port)
                    except Exception:
                        pass
                continue
            raise ValueError(f"Unsupported cache setting '{key}'")
        cfg = config.model_copy(update=update) if update else config
        return RedisCacheService(cfg)

    raise ValueError(f"Unsupported cache BACKEND: {backend}")

__all__ = ["get_cache", "CacheService", "RedisCacheService"]
