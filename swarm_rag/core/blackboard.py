"""
Blackboard lifecycle manager.

Responsible for:
- Creating a fresh BlackboardState for each query
- Cleaning up state after the response is delivered
- (Future) persisting execution traces to SQLite for observability
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from swarm_rag.schemas.blackboard_schema import BlackboardState

logger = logging.getLogger(__name__)


class Blackboard:
    """
    Factory and lifecycle manager for BlackboardState objects.

    Usage:
        async with Blackboard.session(query, session_id) as state:
            state = await scheduler.execute(phases, plugin_map, state)
        # state is auto-cleaned after the block
    """

    @staticmethod
    def create(
        user_query: str,
        session_id: Optional[str] = None,
    ) -> BlackboardState:
        """
        Create a fresh BlackboardState for a new query.

        Args:
            user_query:  The raw (sanitized) user query string.
            session_id:  Caller-supplied session ID; auto-generated if None.
        """
        sid = session_id or str(uuid.uuid4())
        ts = datetime.now(tz=timezone.utc).isoformat()
        state = BlackboardState(
            user_query=user_query,
            session_id=sid,
            timestamp=ts,
        )
        logger.debug("Blackboard created for session=%s query='%.80s…'", sid, user_query)
        return state

    @staticmethod
    def cleanup(state: BlackboardState) -> None:
        """
        Release sensitive fields from a completed state.

        Called after the final response has been delivered to the caller.
        Clears PII entity maps and intermediate retrieval results to avoid
        leaking data across requests when state objects are reused accidentally.
        """
        state.entity_map.clear()
        state.retrieval.weaviate_hits.clear()
        state.retrieval.neo4j_hits.clear()
        state.retrieval.memory_hits.clear()
        state.tool_results.clear()
        logger.debug("Blackboard cleaned up for session=%s", state.session_id)

    class session:
        """Async context manager that creates and cleans up a BlackboardState."""

        def __init__(self, user_query: str, session_id: Optional[str] = None) -> None:
            self._query = user_query
            self._session_id = session_id
            self.state: Optional[BlackboardState] = None

        async def __aenter__(self) -> BlackboardState:
            self.state = Blackboard.create(self._query, self._session_id)
            return self.state

        async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
            if self.state is not None:
                Blackboard.cleanup(self.state)
            return False  # do not suppress exceptions
