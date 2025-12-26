#!/usr/bin/env python3
"""Cleanup script for expired artifacts.

Executed by systemd timer every 6 hours to clean up artifacts
that have exceeded their TTL (48 hours).

Usage:
    python -m src.memory.artifacts.cleanup
"""
import logging
import sys

from src.memory.artifacts.manager import create_artifact_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def main() -> int:
    """Main cleanup function.

    Returns:
        Exit code (0 = success, 1 = error)
    """
    try:
        logger.info("Starting artifact cleanup...")

        # Create artifact manager
        manager = create_artifact_manager()

        # Get stats before cleanup
        stats_before = manager.get_stats()
        logger.info(
            f"Before cleanup: {stats_before['total_threads']} threads, "
            f"{stats_before['total_files']} files, "
            f"{stats_before['total_size_mb']:.2f} MB"
        )

        # Run cleanup
        deleted_count = manager.cleanup_expired()

        # Get stats after cleanup
        stats_after = manager.get_stats()
        logger.info(
            f"After cleanup: {stats_after['total_threads']} threads, "
            f"{stats_after['total_files']} files, "
            f"{stats_after['total_size_mb']:.2f} MB"
        )

        # Calculate freed space
        freed_mb = stats_before['total_size_mb'] - stats_after['total_size_mb']

        logger.info(
            f"Cleanup completed: {deleted_count} items deleted, "
            f"{freed_mb:.2f} MB freed"
        )

        return 0

    except Exception as e:
        logger.error(f"Cleanup failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())