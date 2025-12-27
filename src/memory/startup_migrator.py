"""Startup migrator for Redis conversations to ChatMemory.

Scans Redis for conversations older than 24 hours and exports them
to Weaviate as ChatMemory snapshots for cross-chat retrieval.
"""
import time
from typing import Any, Dict, List, Optional
from langgraph.checkpoint.redis import RedisSaver
from src.rag.audit import get_logger

log = get_logger(__name__)


class StartupMigrator:
    """Migrates old Redis conversations to ChatMemory on startup.

    Attributes:
        checkpointer: RedisSaver instance for accessing Redis conversations
        chat_memory_manager: ChatMemoryManager for saving snapshots
        snapshot_scheduler: SnapshotScheduler to track migrated threads
        age_threshold: Minimum age in seconds for migration (default: 24h)
    """

    def __init__(
        self,
        checkpointer: RedisSaver,
        chat_memory_manager,
        snapshot_scheduler,
        age_threshold: int = 86400,  # 24 hours
    ):
        """Initialize startup migrator.

        Args:
            checkpointer: Redis checkpointer for accessing stored states
            chat_memory_manager: ChatMemoryManager instance
            snapshot_scheduler: SnapshotScheduler instance
            age_threshold: Minimum age in seconds for migration (default: 86400 = 24h)
        """
        self.checkpointer = checkpointer
        self.chat_memory_manager = chat_memory_manager
        self.snapshot_scheduler = snapshot_scheduler
        self.age_threshold = age_threshold
        log.info(
            "StartupMigrator initialized (threshold: %.1f hours)",
            age_threshold / 3600
        )

    def migrate_old_conversations(self) -> Dict[str, Any]:
        """Scan Redis and migrate conversations older than threshold.

        Returns:
            Dict with migration statistics:
                - scanned: Total conversations scanned
                - migrated: Conversations successfully migrated
                - skipped: Conversations skipped (too new or already migrated)
                - errors: Conversations that failed migration
        """
        start_time = time.time()
        log.info("Starting migration of conversations older than %.1f hours...", self.age_threshold / 3600)

        stats = {
            "scanned": 0,
            "migrated": 0,
            "skipped": 0,
            "errors": 0,
        }

        try:
            # Get all checkpoint namespaces (each namespace is a thread_id)
            # LangGraph stores checkpoints as: checkpoint:<namespace>:<thread_id>
            # We need to scan Redis keys directly
            from redis import Redis
            redis_client: Redis = self.checkpointer._redis

            # Scan all checkpoint keys
            cursor = 0
            now = time.time()

            while True:
                cursor, keys = redis_client.scan(cursor, match="checkpoint:*", count=100)

                for key in keys:
                    stats["scanned"] += 1
                    key_str = key.decode('utf-8') if isinstance(key, bytes) else key

                    try:
                        # Extract thread_id from key
                        # Format: checkpoint:<namespace>:<thread_id>
                        parts = key_str.split(":")
                        if len(parts) < 3:
                            log.debug("Skipping malformed key: %s", key_str)
                            stats["skipped"] += 1
                            continue

                        thread_id = parts[2]

                        # Get checkpoint data
                        checkpoint_data = redis_client.get(key)
                        if not checkpoint_data:
                            stats["skipped"] += 1
                            continue

                        # Try to extract timestamp from checkpoint metadata
                        # LangGraph stores checkpoint with metadata including timestamp
                        import pickle
                        checkpoint = pickle.loads(checkpoint_data)

                        # Get timestamp from checkpoint metadata
                        timestamp = checkpoint.get("ts")
                        if not timestamp:
                            log.debug("No timestamp in checkpoint for thread %s", thread_id[:16])
                            stats["skipped"] += 1
                            continue

                        # Check age
                        age = now - timestamp
                        if age < self.age_threshold:
                            log.debug("Thread %s too new (%.1f hours)", thread_id[:16], age / 3600)
                            stats["skipped"] += 1
                            continue

                        # Check if already migrated (snapshot exists in scheduler)
                        if not self.snapshot_scheduler.should_create_snapshot(thread_id):
                            log.debug("Thread %s already has recent snapshot", thread_id[:16])
                            stats["skipped"] += 1
                            continue

                        # Migrate this conversation
                        success = self._migrate_conversation(thread_id, checkpoint, timestamp)
                        if success:
                            stats["migrated"] += 1
                            log.info(
                                "Migrated thread %s (age: %.1f hours)",
                                thread_id[:16],
                                age / 3600
                            )
                        else:
                            stats["errors"] += 1

                    except Exception as e:
                        log.error("Error processing key %s: %s", key_str, e, exc_info=True)
                        stats["errors"] += 1

                # Check if scan is complete
                if cursor == 0:
                    break

        except Exception as e:
            log.error("Error during migration scan: %s", e, exc_info=True)

        elapsed = time.time() - start_time
        log.info(
            "Migration complete: scanned=%d, migrated=%d, skipped=%d, errors=%d (%.2f seconds)",
            stats["scanned"],
            stats["migrated"],
            stats["skipped"],
            stats["errors"],
            elapsed
        )

        return stats

    def _migrate_conversation(
        self,
        thread_id: str,
        checkpoint: Dict[str, Any],
        timestamp: float,
    ) -> bool:
        """Migrate a single conversation to ChatMemory.

        Args:
            thread_id: Conversation thread ID
            checkpoint: LangGraph checkpoint data
            timestamp: Checkpoint timestamp

        Returns:
            True if migration successful, False otherwise
        """
        try:
            from src.memory.core.state import create_initial_state
            from src.memory.snapshot import create_snapshot

            # Extract state from checkpoint
            channel_values = checkpoint.get("channel_values", {})

            # Get user_id and messages
            user_id = channel_values.get("user_id")
            messages = channel_values.get("messages", [])

            if not user_id:
                log.warning("No user_id in checkpoint for thread %s", thread_id[:16])
                return False

            if not messages:
                log.debug("No messages in checkpoint for thread %s", thread_id[:16])
                return False

            # Build state
            state = create_initial_state(user_id, thread_id)
            state["messages"] = messages

            # Copy other state fields if present
            if "tool_memory" in channel_values:
                state["tool_memory"] = channel_values["tool_memory"]
            if "summary" in channel_values:
                state["summary"] = channel_values["summary"]

            # Create snapshot
            snapshot = create_snapshot(
                state=state,
                user_id=user_id,
                thread_id=thread_id,
                ttl_days=30,
            )

            # Save to Weaviate
            success = self.chat_memory_manager.persistence.save_snapshot(snapshot)

            if success:
                # Mark as migrated in scheduler
                self.snapshot_scheduler.mark_snapshot_created(thread_id, timestamp)
                return True
            else:
                log.warning("Failed to save snapshot for thread %s", thread_id[:16])
                return False

        except Exception as e:
            log.error("Error migrating thread %s: %s", thread_id[:16], e, exc_info=True)
            return False


def migrate_redis_conversations_on_startup(
    checkpointer: RedisSaver,
    chat_memory_manager,
    snapshot_scheduler,
    age_threshold: int = 86400,
) -> Dict[str, Any]:
    """Convenience function to run migration on startup.

    Args:
        checkpointer: Redis checkpointer instance
        chat_memory_manager: ChatMemoryManager instance
        snapshot_scheduler: SnapshotScheduler instance
        age_threshold: Minimum age in seconds (default: 24h)

    Returns:
        Migration statistics dict
    """
    migrator = StartupMigrator(
        checkpointer=checkpointer,
        chat_memory_manager=chat_memory_manager,
        snapshot_scheduler=snapshot_scheduler,
        age_threshold=age_threshold,
    )
    return migrator.migrate_old_conversations()


__all__ = [
    "StartupMigrator",
    "migrate_redis_conversations_on_startup",
]
