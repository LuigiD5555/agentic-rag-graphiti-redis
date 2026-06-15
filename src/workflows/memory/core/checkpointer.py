"""SQLite checkpointer with intelligent TTL management."""

import json
import logging
import time
from typing import Any, Optional

from src.backends.storage.sqlite.manager import get_sqlite_manager

logger = logging.getLogger(__name__)


class SQLiteCheckpointer:
    """SQLite-backed checkpointer with TTL refresh on access."""

    def __init__(
        self,
        ttl_seconds: int = 172800,
    ):
        self.ttl = ttl_seconds
        self.sqlite_manager = get_sqlite_manager()

        logger.info(
            "SQLiteCheckpointer initialized with TTL=%ss (%.1fh)",
            ttl_seconds,
            ttl_seconds / 3600,
        )

    def _extract_keys(self, config: dict) -> Optional[tuple[str, str]]:
        configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
        thread_id = configurable.get("thread_id")
        checkpoint_ns = configurable.get("checkpoint_ns", "default")
        if not thread_id:
            return None
        return str(thread_id), str(checkpoint_ns)

    def put(
        self,
        config: dict,
        checkpoint: dict,
        metadata: dict,
        new_versions: Optional[dict] = None,
    ) -> dict:
        """Save checkpoint with TTL."""
        keys = self._extract_keys(config)
        if not keys:
            logger.warning("Missing thread_id in checkpoint config")
            return config

        thread_id, checkpoint_ns = keys
        now_ts = int(time.time())
        expires_at = now_ts + self.ttl

        payload_json = json.dumps(checkpoint)
        metadata_json = json.dumps(metadata)

        with self.sqlite_manager.control_plane.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO memory_checkpoints
                (thread_id, checkpoint_ns, payload_json, metadata_json, version, updated_at, expires_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(thread_id, checkpoint_ns) DO UPDATE SET
                    payload_json = excluded.payload_json,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at,
                    expires_at = excluded.expires_at
                """,
                (thread_id, checkpoint_ns, payload_json, metadata_json, now_ts, expires_at),
            )

        return config

    def get(self, config: dict) -> Optional[dict]:
        """Retrieve checkpoint and extend TTL."""
        keys = self._extract_keys(config)
        if not keys:
            logger.warning("Missing thread_id in checkpoint config")
            return None

        thread_id, checkpoint_ns = keys
        now_ts = int(time.time())
        with self.sqlite_manager.control_plane.get_connection() as conn:
            row = conn.execute(
                """
                SELECT payload_json, expires_at
                FROM memory_checkpoints
                WHERE thread_id = ? AND checkpoint_ns = ?
                """,
                (thread_id, checkpoint_ns),
            ).fetchone()

            if not row:
                return None

            payload_json, expires_at = row
            if int(expires_at) < now_ts:
                conn.execute(
                    "DELETE FROM memory_checkpoints WHERE thread_id = ? AND checkpoint_ns = ?",
                    (thread_id, checkpoint_ns),
                )
                return None

            # Extend TTL (touch)
            new_expires_at = now_ts + self.ttl
            conn.execute(
                """
                UPDATE memory_checkpoints
                SET expires_at = ?, updated_at = ?
                WHERE thread_id = ? AND checkpoint_ns = ?
                """,
                (new_expires_at, now_ts, thread_id, checkpoint_ns),
            )

        try:
            return json.loads(payload_json)
        except Exception as exc:
            logger.error("Failed to decode checkpoint JSON: %s", exc)
            return None

    def get_ttl(self, thread_id: str, checkpoint_ns: str = "default") -> Optional[int]:
        """Get remaining TTL for a thread."""
        now_ts = int(time.time())
        with self.sqlite_manager.control_plane.get_connection() as conn:
            row = conn.execute(
                """
                SELECT expires_at FROM memory_checkpoints
                WHERE thread_id = ? AND checkpoint_ns = ?
                """,
                (thread_id, checkpoint_ns),
            ).fetchone()

        if not row:
            return None

        expires_at = int(row[0])
        remaining = expires_at - now_ts
        return remaining if remaining > 0 else None


def create_checkpointer(
    ttl_seconds: int = 172800,
) -> SQLiteCheckpointer:
    """Factory function to create SQLite checkpointer."""
    return SQLiteCheckpointer(ttl_seconds=ttl_seconds)
