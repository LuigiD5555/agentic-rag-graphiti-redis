"""Automatic snapshot creation scheduler for ChatMemory.

Tracks when snapshots were last created and triggers creation every 24 hours.
"""
import time
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


class SnapshotScheduler:
    """Tracks last snapshot creation time per thread and triggers snapshots every 24h.

    This scheduler maintains in-memory state of when snapshots were last created
    for each conversation thread. When a conversation receives new messages, it
    checks if 24 hours have passed since the last snapshot and triggers creation
    if needed.

    Attributes:
        snapshot_interval: Seconds between automatic snapshots (default: 86400 = 24h)
        last_snapshot_times: Dict mapping thread_id -> timestamp of last snapshot
    """

    def __init__(self, snapshot_interval: int = 86400):
        """Initialize snapshot scheduler.

        Args:
            snapshot_interval: Seconds between snapshots (default: 86400 = 24 hours)
        """
        self.snapshot_interval = snapshot_interval
        self.last_snapshot_times: Dict[str, float] = {}
        logger.info("SnapshotScheduler initialized with interval=%d seconds", snapshot_interval)

    def should_create_snapshot(self, thread_id: str) -> bool:
        """Check if a snapshot should be created for this thread.

        A snapshot should be created if:
        1. No snapshot has been created yet for this thread, OR
        2. More than snapshot_interval seconds have passed since last snapshot

        Args:
            thread_id: Conversation thread ID

        Returns:
            True if snapshot should be created, False otherwise
        """
        now = time.time()
        last_time = self.last_snapshot_times.get(thread_id)

        if last_time is None:
            # No snapshot yet - should create
            logger.debug("Thread %s has no snapshot yet, should create", thread_id[:16])
            return True

        elapsed = now - last_time
        should_create = elapsed >= self.snapshot_interval

        if should_create:
            logger.info(
                "Thread %s last snapshot %.1f hours ago, triggering creation",
                thread_id[:16],
                elapsed / 3600
            )

        return should_create

    def mark_snapshot_created(self, thread_id: str, timestamp: Optional[float] = None):
        """Mark that a snapshot was created for this thread.

        Args:
            thread_id: Conversation thread ID
            timestamp: Snapshot creation time (defaults to current time)
        """
        ts = timestamp or time.time()
        self.last_snapshot_times[thread_id] = ts
        logger.debug("Marked snapshot created for thread %s at %s", thread_id[:16], ts)

    def cleanup_old_entries(self, max_age: int = 604800):
        """Remove tracking entries for threads with no recent snapshots.

        This prevents memory leak from tracking threads that are no longer active.

        Args:
            max_age: Remove entries older than this many seconds (default: 7 days)
        """
        now = time.time()
        cutoff = now - max_age

        old_threads = [
            thread_id
            for thread_id, ts in self.last_snapshot_times.items()
            if ts < cutoff
        ]

        for thread_id in old_threads:
            del self.last_snapshot_times[thread_id]

        if old_threads:
            logger.info("Cleaned up %d old thread tracking entries", len(old_threads))

    def get_stats(self) -> Dict[str, int]:
        """Get scheduler statistics.

        Returns:
            Dict with tracking stats (tracked_threads, etc.)
        """
        return {
            "tracked_threads": len(self.last_snapshot_times),
            "snapshot_interval_hours": self.snapshot_interval / 3600,
        }


# Global scheduler instance (initialized in app lifespan)
_global_scheduler: Optional[SnapshotScheduler] = None


def get_snapshot_scheduler() -> SnapshotScheduler:
    """Get global snapshot scheduler instance.

    Returns:
        Global SnapshotScheduler instance

    Raises:
        RuntimeError: If scheduler not initialized
    """
    if _global_scheduler is None:
        raise RuntimeError("SnapshotScheduler not initialized")
    return _global_scheduler


def create_snapshot_scheduler(snapshot_interval: int = 86400) -> SnapshotScheduler:
    """Create and register global snapshot scheduler.

    Args:
        snapshot_interval: Seconds between snapshots (default: 24 hours)

    Returns:
        SnapshotScheduler instance
    """
    global _global_scheduler
    _global_scheduler = SnapshotScheduler(snapshot_interval=snapshot_interval)
    return _global_scheduler


__all__ = [
    "SnapshotScheduler",
    "get_snapshot_scheduler",
    "create_snapshot_scheduler",
]
