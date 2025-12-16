"""
Cache backends (Redis by default).

This module builds the cache service using a Django-like `CACHES` registry, but
also supports runtime overrides via environment variables, which is critical
when the application container runs with `network_mode: host` (or equivalent),
where Compose service DNS names (e.g., `redis`) are not available.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from src.rag.interfaces.cache_interface import CacheServiceProtocol

from .redis_cache import CacheService as RedisCacheService


@dataclass(frozen=True, slots=True)
class RedisEndpoint:
    """
    Value object representing a Redis TCP endpoint.
    """

    host: str
    port: int


class CacheFactory:
    """
    Build cache backends from application configuration.
    """

    def create_cache(self, config: Any, alias: str = "default") -> CacheServiceProtocol:
        """
        Create the cache backend instance for the given alias.

        Precedence:
            1) Environment variables (REDIS_URL or REDIS_HOST/REDIS_PORT)
            2) CACHES[alias]["LOCATION"] if it starts with redis://

        Args:
            config: Configuration object that must expose a `CACHES` mapping and
                ideally provide `copy(update=...)` (pydantic-style). If `copy`
                is not available, the factory will attempt to set attributes
                directly on the object.
            alias: Cache alias inside config.CACHES.

        Returns:
            An instance implementing CacheServiceProtocol.

        Raises:
            KeyError: If the alias does not exist in CACHES.
            TypeError: If CACHES is not a dict-like mapping, or config cannot be updated.
            ValueError: If Redis endpoint cannot be determined or is invalid.
        """
        cache_config = self._get_cache_config(config, alias)
        redis_endpoint = self._resolve_redis_endpoint(cache_config)
        updated_config = self._apply_config_update(
            config,
            {"REDIS_HOST": redis_endpoint.host, "REDIS_PORT": redis_endpoint.port},
        )
        return RedisCacheService(updated_config)

    def _get_cache_config(self, config: Any, alias: str) -> Mapping[str, Any]:
        """
        Fetch and validate the cache configuration for the given alias.
        """
        caches = getattr(config, "CACHES", None)
        if not isinstance(caches, dict):
            raise TypeError("config.CACHES must be a dict mapping cache aliases to dict settings")

        if alias not in caches:
            available_aliases = ", ".join(sorted(caches.keys())) or "<none>"
            raise KeyError(f"Unknown cache alias '{alias}'. Available: {available_aliases}")

        cache_config = caches[alias]
        if not isinstance(cache_config, dict):
            raise TypeError(f"config.CACHES['{alias}'] must be a dict of settings")

        return cache_config

    def _resolve_redis_endpoint(self, cache_config: Mapping[str, Any]) -> RedisEndpoint:
        """
        Determine Redis endpoint using env vars first, then LOCATION.
        """
        endpoint_from_env = self._redis_endpoint_from_environment()
        if endpoint_from_env is not None:
            return endpoint_from_env

        location = str(cache_config.get("LOCATION") or "").strip()
        endpoint_from_location = self._redis_endpoint_from_location(location)
        if endpoint_from_location is not None:
            return endpoint_from_location

        raise ValueError(
            "Redis endpoint not configured. Set REDIS_URL or REDIS_HOST/REDIS_PORT, "
            "or configure CACHES['default']['LOCATION'] as redis://host:port/0"
        )

    def _redis_endpoint_from_environment(self) -> RedisEndpoint | None:
        """
        Read REDIS_URL or REDIS_HOST/REDIS_PORT from environment variables.
        """
        redis_url = (os.getenv("REDIS_URL") or "").strip()
        if redis_url:
            return self._parse_redis_url(redis_url)

        redis_host = (os.getenv("REDIS_HOST") or "").strip()
        redis_port_text = (os.getenv("REDIS_PORT") or "").strip()

        if not redis_host and not redis_port_text:
            return None

        if not redis_host:
            raise ValueError("REDIS_HOST is required when REDIS_PORT is provided")

        if not redis_port_text:
            raise ValueError("REDIS_PORT is required when REDIS_HOST is provided")

        try:
            redis_port = int(redis_port_text)
        except ValueError as exc:
            raise ValueError("REDIS_PORT must be an integer") from exc

        return RedisEndpoint(host=redis_host, port=redis_port)

    def _redis_endpoint_from_location(self, location: str) -> RedisEndpoint | None:
        """
        Parse a redis:// URL from the LOCATION setting.
        """
        if not location.startswith("redis://"):
            return None
        return self._parse_redis_url(location)

    def _parse_redis_url(self, redis_url: str) -> RedisEndpoint:
        """
        Parse a redis://host:port/db URL string into a RedisEndpoint.
        """
        parsed = urlparse(redis_url)
        if parsed.scheme != "redis":
            raise ValueError("Redis URL must start with redis://")

        if not parsed.hostname:
            raise ValueError("Redis URL must include a hostname")

        if parsed.port is None:
            raise ValueError("Redis URL must include a port")

        return RedisEndpoint(host=parsed.hostname, port=int(parsed.port))

    def _apply_config_update(self, config: Any, update: dict[str, Any]) -> Any:
        """
        Apply a configuration update in the cleanest available way.

        Preference:
            1) config.copy(update=...)
            2) setattr for each key

        Raises:
            TypeError: If config cannot be updated.
        """
        copy_method = getattr(config, "copy", None)
        if callable(copy_method):
            return copy_method(update=update)

        for key, value in update.items():
            try:
                setattr(config, key, value)
            except (AttributeError, TypeError) as exc:
                raise TypeError(
                    "Config object does not support copy(update=...) and does not allow attribute assignment"
                ) from exc

        return config


_FACTORY = CacheFactory()


def get_cache(config: Any, alias: str = "default") -> CacheServiceProtocol:
    """
    Module-level convenience wrapper around CacheFactory.
    """
    return _FACTORY.create_cache(config, alias=alias)


__all__ = ["get_cache", "CacheFactory", "RedisCacheService"]
