"""Background cleanup scheduler for temporal tenants.

Periodically cleans up expired temporal tenants based on TTL.
"""
import logging
import threading
import time
from typing import Optional

import redis
import weaviate

from src.rag.temporal.tenant_manager import TemporalTenantManager

logger = logging.getLogger(__name__)


class TemporalCleanupScheduler:
    """Background scheduler for cleaning up expired temporal tenants."""

    def __init__(
        self,
        tenant_manager: TemporalTenantManager,
        redis_client: redis.Redis,
        cleanup_interval: int = 3600,
        tenant_ttl_key_prefix: str = "tenant_created:",
    ):
        """Initialize cleanup scheduler.

        Args:
            tenant_manager: TemporalTenantManager instance
            redis_client: Redis client for timestamp tracking
            cleanup_interval: Cleanup interval in seconds (default: 1 hour)
            tenant_ttl_key_prefix: Redis key prefix for tenant timestamps
        """
        self.tenant_manager = tenant_manager
        self.redis_client = redis_client
        self.cleanup_interval = cleanup_interval
        self.tenant_ttl_key_prefix = tenant_ttl_key_prefix

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        logger.info(
            f"TemporalCleanupScheduler initialized: interval={cleanup_interval}s"
        )

    def start(self):
        """Start the cleanup scheduler in a background thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Cleanup scheduler already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

        logger.info("Cleanup scheduler started")

    def stop(self):
        """Stop the cleanup scheduler."""
        if self._thread is None or not self._thread.is_alive():
            logger.warning("Cleanup scheduler not running")
            return

        self._stop_event.set()
        self._thread.join(timeout=5)

        logger.info("Cleanup scheduler stopped")

    def _run(self):
        """Background thread that runs cleanup periodically."""
        logger.info(f"Cleanup scheduler thread started (interval={self.cleanup_interval}s)")

        while not self._stop_event.is_set():
            try:
                # Run cleanup
                deleted_count = self.tenant_manager.cleanup_expired_tenants(
                    redis_client=self.redis_client,
                    tenant_ttl_key_prefix=self.tenant_ttl_key_prefix,
                )

                if deleted_count > 0:
                    logger.info(f"Cleanup: deleted {deleted_count} expired tenants")
                else:
                    logger.debug("Cleanup: no expired tenants to delete")

            except Exception as e:
                logger.error(f"Cleanup failed: {e}", exc_info=True)

            # Wait for next interval (or stop signal)
            self._stop_event.wait(self.cleanup_interval)

        logger.info("Cleanup scheduler thread stopped")


def create_temporal_cleanup_scheduler(
    tenant_manager: TemporalTenantManager,
    redis_client: redis.Redis,
    cleanup_interval: int = 3600,
) -> TemporalCleanupScheduler:
    """Factory function to create TemporalCleanupScheduler.

    Args:
        tenant_manager: TemporalTenantManager instance
        redis_client: Redis client
        cleanup_interval: Cleanup interval in seconds

    Returns:
        TemporalCleanupScheduler instance
    """
    return TemporalCleanupScheduler(
        tenant_manager=tenant_manager,
        redis_client=redis_client,
        cleanup_interval=cleanup_interval,
    )
