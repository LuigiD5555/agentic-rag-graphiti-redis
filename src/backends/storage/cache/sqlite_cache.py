"""SQLite-backed cache service (legacy Redis module)."""

import json
import time
from typing import Optional, Any

from src.backends.storage.sqlite.manager import get_sqlite_manager


class SQLiteCacheService:
    """Simple key-value cache backed by SQLite."""

    def __init__(self):
        self.sqlite_manager = get_sqlite_manager()
        self.control_plane = self.sqlite_manager.control_plane

    def _now(self) -> int:
        return int(time.time())

    def _purge_expired(self) -> None:
        now_ts = self._now()
        with self.control_plane.get_connection() as conn:
            conn.execute("DELETE FROM cache_kv WHERE expires_at <= ?", (now_ts,))

    def get(self, key: str) -> Optional[str]:
        self._purge_expired()
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute(
                "SELECT value_json FROM cache_kv WHERE cache_key = ?",
                (key,),
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def set(self, key: str, value: Any, ttl: int = 3600) -> None:
        expires_at = self._now() + int(ttl)
        payload = json.dumps(value)
        with self.control_plane.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO cache_kv (cache_key, value_json, expires_at)
                VALUES (?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    value_json = excluded.value_json,
                    expires_at = excluded.expires_at
                """,
                (key, payload, expires_at),
            )


__all__ = ["SQLiteCacheService"]
