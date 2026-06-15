"""
Blackboard lifecycle manager.

Responsible for:
- Creating a fresh BlackboardState for each query
- Persisting state snapshots to SQLite after each pipeline layer
- Cleaning up (deleting) session rows from SQLite after the response is delivered
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from experiments.swarm_rag.schemas.blackboard_schema import BlackboardState
from experiments.swarm_rag.core.blackboard_repository import BlackboardRepository

logger = logging.getLogger(__name__)


class Blackboard:
    """
    Factory and lifecycle manager for BlackboardState objects.

    Persists all state transitions to SQLite so that multiple async workers
    share a coherent view and crashed sessions can be inspected post-mortem.

    Usage (single-worker, context-manager style):
        async with Blackboard.session(query, session_id) as (state, board):
            state = await run_perception(query, state)
            board.checkpoint(state, "perception")
            ...
        # session row is deleted from SQLite after the block

    Usage (manual):
        state = Blackboard.create(query)
        board = BlackboardRepository()
        board.open_session(state.session_id, state.user_query)
        ...
        board.persist_state(state, "pipeline")
        Blackboard.cleanup(state, board)
    """

    @staticmethod
    def create(
        user_query: str,
        session_id: Optional[str] = None,
        repository: Optional[BlackboardRepository] = None,
    ) -> BlackboardState:
        """
        Create a fresh BlackboardState and register it in SQLite.

        Args:
            user_query:   The raw (sanitized) user query string.
            session_id:   Caller-supplied session ID; auto-generated if None.
            repository:   BlackboardRepository to use; a default instance is
                          created if None.

        Returns:
            A new BlackboardState whose session is already open in SQLite.
        """
        sid = session_id or str(uuid.uuid4())
        ts = datetime.now(tz=timezone.utc).isoformat()
        state = BlackboardState(
            user_query=user_query,
            session_id=sid,
            timestamp=ts,
        )
        repo = repository or BlackboardRepository()
        repo.open_session(sid, user_query)
        logger.debug("Blackboard created for session=%s query='%.80s…'", sid, user_query)
        return state

    @staticmethod
    def cleanup(
        state: BlackboardState,
        repository: Optional[BlackboardRepository] = None,
    ) -> None:
        """
        Delete the session from SQLite and clear sensitive in-memory fields.

        Called after the final response has been delivered to the caller.
        Clears PII entity fields and intermediate retrieval results to prevent
        data leakage if the state object is accidentally reused.

        Args:
            state:      The BlackboardState to clean up.
            repository: BlackboardRepository to use; a default instance is
                        created if None.
        """
        repo = repository or BlackboardRepository()
        repo.delete_session(state.session_id)

        # Clear sensitive in-memory fields
        state.retrieval.weaviate_hits.clear()
        state.retrieval.neo4j_hits.clear()
        state.retrieval.memory_hits.clear()
        state.retrieval.version_conflicts.clear()
        state.specialists.extracted_facts.clear()
        state.active_branches.clear()
        logger.debug("Blackboard cleaned up for session=%s", state.session_id)

    class session:
        """
        Async context manager that creates, persists, and cleans up a BlackboardState.

        Yields a (state, repository) tuple so the caller can checkpoint state
        after each layer without constructing a second repository instance.

        Example::

            async with Blackboard.session(query) as (state, board):
                state = await run_perception(query, state)
                board.checkpoint(state, "perception")
        """

        def __init__(self, user_query: str, session_id: Optional[str] = None) -> None:
            self._query = user_query
            self._session_id = session_id
            self._repo = BlackboardRepository()
            self.state: Optional[BlackboardState] = None

        async def __aenter__(self) -> tuple[BlackboardState, BlackboardRepository]:
            self.state = Blackboard.create(
                self._query,
                session_id=self._session_id,
                repository=self._repo,
            )
            return self.state, self._repo

        async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
            if self.state is not None:
                if exc_type is None:
                    # Persist final state before cleanup for post-mortem observability
                    self._repo.persist_state(self.state, written_by="pipeline_exit")
                Blackboard.cleanup(self.state, repository=self._repo)
            return False  # do not suppress exceptions
