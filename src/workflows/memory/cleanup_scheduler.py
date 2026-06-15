"""Background cleanup scheduler for expired ChatMemory snapshots.

Runs periodic cleanup of expired snapshots and old scheduler tracking entries.
"""
import asyncio
import time
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class CleanupScheduler:
    """Background scheduler for periodic cleanup tasks.

    Runs two cleanup tasks:
    1. Remove expired ChatMemory snapshots from Weaviate (TTL expired)
    2. Remove old thread tracking entries from SnapshotScheduler (inactive threads)

    Attributes:
        chat_memory_manager: ChatMemoryManager instance for snapshot cleanup
        snapshot_scheduler: SnapshotScheduler instance for tracking cleanup
        cleanup_interval: Seconds between cleanup runs (default: 3600 = 1 hour)
        running: Whether cleanup loop is currently running
    """

    def __init__(
        self,
        chat_memory_manager,
        snapshot_scheduler,
        cleanup_interval: int = 3600,
    ):
        """Initialize cleanup scheduler.

        Args:
            chat_memory_manager: ChatMemoryManager instance
            snapshot_scheduler: SnapshotScheduler instance
            cleanup_interval: Seconds between cleanup runs (default: 3600 = 1 hour)
        """
        self.chat_memory_manager = chat_memory_manager
        self.snapshot_scheduler = snapshot_scheduler
        self.cleanup_interval = cleanup_interval
        self.running = False
        self._task: Optional[asyncio.Task] = None
        logger.info(
            "CleanupScheduler initialized with interval=%d seconds (%.1f hours)",
            cleanup_interval,
            cleanup_interval / 3600
        )

    async def start(self):
        """Start background cleanup loop."""
        if self.running:
            logger.warning("CleanupScheduler already running")
            return

        self.running = True
        self._task = asyncio.create_task(self._cleanup_loop())
        logger.info("CleanupScheduler started")

    async def stop(self):
        """Stop background cleanup loop."""
        if not self.running:
            return

        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("CleanupScheduler stopped")

    async def _cleanup_loop(self):
        """Background loop that runs cleanup tasks periodically."""
        logger.info("Cleanup loop started, will run every %.1f hours", self.cleanup_interval / 3600)

        while self.running:
            try:
                # Sleep first (don't run cleanup immediately on startup)
                await asyncio.sleep(self.cleanup_interval)

                if not self.running:
                    break

                # Run cleanup tasks
                await self._run_cleanup()

            except asyncio.CancelledError:
                logger.info("Cleanup loop cancelled")
                break
            except Exception as e:
                logger.error("Error in cleanup loop: %s", e, exc_info=True)
                # Continue running even if cleanup fails

    async def _run_cleanup(self):
        """Execute all cleanup tasks."""
        start_time = time.time()
        logger.info("Running scheduled cleanup tasks...")

        # Task 1: Cleanup expired snapshots from Weaviate
        try:
            deleted_snapshots = await asyncio.to_thread(
                self.chat_memory_manager.persistence.cleanup_expired
            )
            logger.info("Deleted %d expired snapshots from Weaviate", deleted_snapshots)
        except Exception as e:
            logger.error("Failed to cleanup expired snapshots: %s", e, exc_info=True)

        # Task 2: Cleanup old thread tracking entries
        try:
            await asyncio.to_thread(
                self.snapshot_scheduler.cleanup_old_entries,
                max_age=604800  # 7 days
            )
            stats = self.snapshot_scheduler.get_stats()
            logger.info(
                "Cleaned up old tracking entries, now tracking %d threads",
                stats["tracked_threads"]
            )
        except Exception as e:
            logger.error("Failed to cleanup old tracking entries: %s", e, exc_info=True)

        elapsed = time.time() - start_time
        logger.info("Cleanup tasks completed in %.2f seconds", elapsed)


# Global cleanup scheduler instance
_global_cleanup_scheduler: Optional[CleanupScheduler] = None


def get_cleanup_scheduler() -> CleanupScheduler:
    """Get global cleanup scheduler instance.

    Returns:
        Global CleanupScheduler instance

    Raises:
        RuntimeError: If scheduler not initialized
    """
    if _global_cleanup_scheduler is None:
        raise RuntimeError("CleanupScheduler not initialized")
    return _global_cleanup_scheduler


def create_cleanup_scheduler(
    chat_memory_manager,
    snapshot_scheduler,
    cleanup_interval: int = 3600,
) -> CleanupScheduler:
    """Create and register global cleanup scheduler.

    Args:
        chat_memory_manager: ChatMemoryManager instance
        snapshot_scheduler: SnapshotScheduler instance
        cleanup_interval: Seconds between cleanup runs (default: 1 hour)

    Returns:
        CleanupScheduler instance
    """
    global _global_cleanup_scheduler
    _global_cleanup_scheduler = CleanupScheduler(
        chat_memory_manager=chat_memory_manager,
        snapshot_scheduler=snapshot_scheduler,
        cleanup_interval=cleanup_interval,
    )
    return _global_cleanup_scheduler


__all__ = [
    "CleanupScheduler",
    "get_cleanup_scheduler",
    "create_cleanup_scheduler",
]
