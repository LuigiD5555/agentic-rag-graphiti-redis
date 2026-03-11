"""
Blackboard SQLite repository.

Persists BlackboardState sessions and their slots to control_plane.db so that
multiple async workers or coroutines share a single coherent view of the query
state.  Each sub-state (perception, retrieval, specialists, reasoning) is stored
as one JSON slot row, plus metadata-only slots for active_branches,
execution_trace, latency_ms, and final_response.

Lifecycle
---------
1. ``open_session()``    — INSERT INTO blackboard_sessions (status='active')
2. ``write_slot()``      — UPSERT a single slot (called after each layer)
3. ``read_state()``      — reconstruct full BlackboardState from all slot rows
4. ``close_session()``   — UPDATE status='done' (keeps rows for observability)
5. ``delete_session()``  — DELETE CASCADE (called from Blackboard.cleanup)

Sessions expire automatically after ``session_ttl_seconds`` (default 1 h) to
handle crashed workers; a background sweep is *not* required because stale rows
are cheap and the DELETE in cleanup() is the primary GC path.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Optional

from src.backends.storage.sqlite.manager import get_sqlite_manager
from experiments.swarm_rag.schemas.blackboard_schema import (
    BlackboardState,
    PerceptionOutput,
    RetrievalOutput,
    SpecialistOutput,
    ReasoningOutput,
)

logger = logging.getLogger(__name__)

# TTL for a blackboard session row.  If the pipeline crashes without calling
# cleanup(), the row expires after this many seconds.
_DEFAULT_SESSION_TTL_SECONDS = 3600  # 1 hour


class BlackboardRepository:
    """
    Thin SQLite repository for blackboard shared state.

    Uses the global SQLiteControlPlaneManager so no extra connection config
    is needed — the same control_plane.db used by ingestion/ledger/queue.
    """

    def __init__(self, session_ttl_seconds: int = _DEFAULT_SESSION_TTL_SECONDS) -> None:
        self._control_plane = get_sqlite_manager().control_plane
        self._session_ttl_seconds = session_ttl_seconds

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def open_session(self, session_id: str, user_query: str) -> None:
        """Register a new active session row."""
        now = int(time.time())
        expires_at = now + self._session_ttl_seconds
        with self._control_plane.get_connection() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO blackboard_sessions
                    (session_id, user_query, status, created_at, expires_at)
                VALUES (?, ?, 'active', ?, ?)
                """,
                (session_id, user_query, now, expires_at),
            )
            conn.commit()
        logger.debug("Blackboard session opened: %s", session_id)

    def close_session(self, session_id: str) -> None:
        """Mark session as done (keeps rows; DELETE is called by cleanup)."""
        with self._control_plane.get_connection() as conn:
            conn.execute(
                "UPDATE blackboard_sessions SET status='done' WHERE session_id=?",
                (session_id,),
            )
            conn.commit()
        logger.debug("Blackboard session closed: %s", session_id)

    def delete_session(self, session_id: str) -> None:
        """Remove session and all its slots (ON DELETE CASCADE)."""
        with self._control_plane.get_connection() as conn:
            conn.execute(
                "DELETE FROM blackboard_sessions WHERE session_id=?",
                (session_id,),
            )
            conn.commit()
        logger.debug("Blackboard session deleted: %s", session_id)

    # ------------------------------------------------------------------
    # Slot write / read
    # ------------------------------------------------------------------

    def write_slot(self, session_id: str, slot_name: str, value: object, written_by: str) -> None:
        """Upsert one slot for the given session."""
        value_json = json.dumps(value, default=str)
        now = int(time.time())
        with self._control_plane.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO blackboard_slots
                    (session_id, slot_name, value_json, written_by, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id, slot_name) DO UPDATE SET
                    value_json = excluded.value_json,
                    written_by = excluded.written_by,
                    updated_at = excluded.updated_at
                """,
                (session_id, slot_name, value_json, written_by, now),
            )
            conn.commit()

    def _read_slots(self, session_id: str) -> dict[str, object]:
        """Return all slots for a session as {slot_name: parsed_value}."""
        with self._control_plane.get_connection() as conn:
            rows = conn.execute(
                "SELECT slot_name, value_json FROM blackboard_slots WHERE session_id=?",
                (session_id,),
            ).fetchall()
        return {slot_name: json.loads(value_json) for slot_name, value_json in rows}

    # ------------------------------------------------------------------
    # Full state persistence helpers
    # ------------------------------------------------------------------

    def persist_state(self, state: BlackboardState, written_by: str) -> None:
        """
        Write all sub-states and metadata slots for *state* to SQLite.

        Callers should invoke this after each pipeline layer completes so that
        the full state is always recoverable from the DB.
        """
        sid = state.session_id
        self.write_slot(sid, "perception", state.perception.model_dump(), written_by)
        self.write_slot(sid, "retrieval", state.retrieval.model_dump(), written_by)
        self.write_slot(sid, "specialists", state.specialists.model_dump(), written_by)
        self.write_slot(sid, "reasoning", state.reasoning.model_dump(), written_by)
        self.write_slot(sid, "active_branches", state.active_branches, written_by)
        self.write_slot(sid, "execution_trace", state.execution_trace, written_by)
        self.write_slot(sid, "latency_ms", state.latency_ms, written_by)
        if state.final_response is not None:
            self.write_slot(sid, "final_response", state.final_response, written_by)

    def load_state(self, session_id: str, user_query: str, timestamp: str) -> Optional[BlackboardState]:
        """
        Reconstruct a BlackboardState from persisted slots.

        Returns None if the session has no slots (e.g. it was already deleted).
        """
        slots = self._read_slots(session_id)
        if not slots:
            return None

        return BlackboardState(
            session_id=session_id,
            user_query=user_query,
            timestamp=timestamp,
            perception=PerceptionOutput(**slots["perception"]) if "perception" in slots else PerceptionOutput(),
            retrieval=RetrievalOutput(**slots["retrieval"]) if "retrieval" in slots else RetrievalOutput(),
            specialists=SpecialistOutput(**slots["specialists"]) if "specialists" in slots else SpecialistOutput(),
            reasoning=ReasoningOutput(**slots["reasoning"]) if "reasoning" in slots else ReasoningOutput(),
            active_branches=slots.get("active_branches", []),
            execution_trace=slots.get("execution_trace", []),
            latency_ms=slots.get("latency_ms", {}),
            final_response=slots.get("final_response"),
        )

    # ------------------------------------------------------------------
    # Housekeeping
    # ------------------------------------------------------------------

    def purge_expired_sessions(self) -> int:
        """Delete sessions whose expires_at has passed.  Returns count deleted."""
        now = int(time.time())
        with self._control_plane.get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM blackboard_sessions WHERE expires_at < ?",
                (now,),
            )
            conn.commit()
            return cursor.rowcount
