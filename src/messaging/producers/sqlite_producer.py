"""SQLite producer for cache-like operations."""

import logging
import uuid
from typing import Any, Optional

from src.backends.storage.cache.sqlite_cache import SQLiteCacheService

logger = logging.getLogger(__name__)


class SQLiteProducer:
    """Producer for cache operations using SQLite."""

    def __init__(self):
        self.cache = SQLiteCacheService()

    async def initialize(self):
        """Initialize producer (no-op for SQLite)."""
        return None

    async def _ensure_ready(self):
        return None

    async def set_key(self, key: str, value: Any, ttl: Optional[int] = None, priority: int = 5) -> str:
        _ = priority
        await self._ensure_ready()
        self.cache.set(key, value, ttl=ttl or 3600)
        msg_id = f"sqlite_set_{uuid.uuid4().hex[:8]}"
        logger.debug("SET key=%s (ttl=%s)", key, ttl)
        return msg_id

    async def get_key(self, key: str, priority: int = 5) -> str:
        _ = priority
        await self._ensure_ready()
        _ = self.cache.get(key)
        msg_id = f"sqlite_get_{uuid.uuid4().hex[:8]}"
        logger.debug("GET key=%s", key)
        return msg_id

    async def delete_key(self, key: str, priority: int = 3) -> str:
        _ = priority
        await self._ensure_ready()
        self.cache.set(key, None, ttl=1)
        msg_id = f"sqlite_del_{uuid.uuid4().hex[:8]}"
        logger.debug("DELETE key=%s", key)
        return msg_id

    async def setex_key(self, key: str, ttl: int, value: Any, priority: int = 5) -> str:
        return await self.set_key(key, value, ttl=ttl, priority=priority)

    async def incr_key(self, key: str, priority: int = 5) -> str:
        _ = priority
        await self._ensure_ready()
        current_raw = self.cache.get(key)
        current = 0
        if current_raw:
            try:
                current = int(current_raw)
            except ValueError:
                current = 0
        current += 1
        self.cache.set(key, current, ttl=3600)
        msg_id = f"sqlite_incr_{uuid.uuid4().hex[:8]}"
        logger.debug("INCR key=%s", key)
        return msg_id

    async def decr_key(self, key: str, priority: int = 5) -> str:
        _ = priority
        await self._ensure_ready()
        current_raw = self.cache.get(key)
        current = 0
        if current_raw:
            try:
                current = int(current_raw)
            except ValueError:
                current = 0
        current -= 1
        self.cache.set(key, current, ttl=3600)
        msg_id = f"sqlite_decr_{uuid.uuid4().hex[:8]}"
        logger.debug("DECR key=%s", key)
        return msg_id

    async def expire_key(self, key: str, ttl: int, priority: int = 5) -> str:
        _ = priority
        await self._ensure_ready()
        value = self.cache.get(key)
        if value is not None:
            self.cache.set(key, value, ttl=ttl)
        msg_id = f"sqlite_expire_{uuid.uuid4().hex[:8]}"
        logger.debug("EXPIRE key=%s ttl=%s", key, ttl)
        return msg_id


_sqlite_producer_instance: Optional[SQLiteProducer] = None


async def get_sqlite_producer() -> SQLiteProducer:
    """Get or create global SQLite producer instance."""
    global _sqlite_producer_instance

    if _sqlite_producer_instance is None:
        _sqlite_producer_instance = SQLiteProducer()
        await _sqlite_producer_instance.initialize()

    return _sqlite_producer_instance


__all__ = ["SQLiteProducer", "get_sqlite_producer"]
