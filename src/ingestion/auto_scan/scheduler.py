"""
Auto-Ingestion Scheduler - Periodically scans directories and triggers ingestion for changed files.

This service runs in the background and periodically executes the ingestion scanner,
which uses Redis cache to efficiently detect only files that have changed (based on
mtime, size, and optionally content hash).

This approach is more efficient than file system watchers because:
- Reuses existing cache infrastructure (Redis-based)
- Scales better with large directories
- More reliable (no missed events)
- Lower resource usage (no inotify watchers)
- Handles batch changes efficiently

How it works:
1. Scanner reads file metadata from Redis cache
2. Compares current mtime/size with cached values
3. Only processes files that changed
4. Updates cache after successful ingestion
"""

import os
import time
import signal
from typing import Optional
from datetime import datetime

from src.rag.audit import get_logger, configure_logging, resolve_level
from src.rag.conf import Config, sync_settings_json
from src.ingestion.orchestrator import IngestionOrchestrator
from src.ingestion.helpers import build_ingestion_options_from_args

logger = get_logger(__name__)


class AutoIngestionScheduler:
    """
    Periodically runs ingestion scanner to detect and process changed files.

    Uses the existing Redis cache system to efficiently skip unchanged files.
    """

    def __init__(
        self,
        config: Config,
        scan_interval: int = 300,  # 5 minutes default
        initial_scan: bool = True,
        initial_wait: int = 30,
        max_files: int = 0
    ):
        """
        Initialize the auto-ingestion scheduler.

        Args:
            config: Configuration object
            scan_interval: Seconds between scans (default: 300 = 5 minutes)
            initial_scan: Whether to run full scan on startup
            initial_wait: Seconds to wait before initial scan (for services to be ready)
        """
        self.config = config
        self.scan_interval = scan_interval
        self.initial_scan = initial_scan
        self.initial_wait = initial_wait
        self.max_files = max_files
        self.orchestrator = IngestionOrchestrator(config)

        # Shutdown flag
        self._running = False
        self._shutdown_requested = False

        # Statistics
        self.total_scans = 0
        self.total_ingested = 0
        self.total_failed = 0
        self.last_scan_time: Optional[datetime] = None
        self.last_scan_duration: float = 0.0

        logger.info(
            "AutoIngestionScheduler initialized: interval=%ss, max_files=%s",
            scan_interval,
            max_files if max_files else "unlimited",
        )

    def run_ingestion_scan(self) -> dict:
        """
        Run a single ingestion scan.

        The scanner uses Redis cache to detect only changed files,
        so this is very efficient even with many files.

        Returns:
            Dictionary with scan results
        """
        from argparse import Namespace

        logger.info("=" * 60)
        logger.info(f"Running scheduled ingestion scan (#{self.total_scans + 1})")
        logger.info("=" * 60)

        start_time = time.time()

        try:
            # Build ingestion options
            # The scanner will use Redis cache to skip unchanged files
            args = Namespace(
                paths=[],  # Will use default paths from config
                exts=None,
                exclude_dirs=None,
                exclude_patterns=None,
                follow_symlinks=False,
                dry_run=False,
                per_file=False,
                streaming=True,  # Stream results as they're found
                max_files=self.max_files,
                scan_progress=100,  # Log every 100 directories
                log_level=None
            )

            options = build_ingestion_options_from_args(args, self.config)
            result = self.orchestrator.run_with_report(options)

            # Update statistics
            self.total_scans += 1
            self.total_ingested += result.get('ingested', 0)
            self.total_failed += result.get('failed', 0)
            self.last_scan_time = datetime.now()
            self.last_scan_duration = time.time() - start_time

            logger.info("=" * 60)
            logger.info("Scan complete:")
            logger.info(f"  Ingested: {result.get('ingested', 0)} files")
            logger.info(f"  Failed: {result.get('failed', 0)} files")
            logger.info(f"  Candidates: {result.get('candidates', 0)} files")
            logger.info(f"  Duration: {self.last_scan_duration:.2f}s")
            logger.info(f"  Total scans: {self.total_scans}")
            logger.info(f"  Total ingested: {self.total_ingested}")
            logger.info("=" * 60)

            return result

        except Exception as e:
            logger.error(f"Scan failed: {e}", exc_info=True)
            self.last_scan_duration = time.time() - start_time
            return {
                "status": "error",
                "error": str(e),
                "ingested": 0,
                "failed": 0,
                "candidates": 0
            }

    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            sig_name = signal.Signals(signum).name
            logger.info(f"Received {sig_name} signal, initiating shutdown...")
            self._shutdown_requested = True

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    def run_forever(self):
        """
        Run the scheduler indefinitely until shutdown is requested.

        This will:
        1. Optionally run initial full scan
        2. Then periodically run scans at the configured interval
        3. Handle graceful shutdown on SIGINT/SIGTERM
        """
        self._setup_signal_handlers()
        self._running = True

        try:
            # Initial scan
            if self.initial_scan:
                logger.info(f"Waiting {self.initial_wait}s for services to be ready...")

                # Allow interruption during wait
                for _ in range(self.initial_wait):
                    if self._shutdown_requested:
                        logger.info("Shutdown requested during initial wait")
                        return
                    time.sleep(1)

                logger.info("Running initial full scan...")
                self.run_ingestion_scan()
            else:
                logger.info("Skipping initial scan (AUTO_INGEST_INITIAL=false)")

            # Periodic scanning loop
            logger.info("")
            logger.info("=" * 60)
            logger.info(f"Starting periodic scanning (every {self.scan_interval}s)")
            logger.info("=" * 60)

            while not self._shutdown_requested:
                # Wait for next scan interval (with periodic checks for shutdown)
                logger.debug(f"Next scan in {self.scan_interval}s...")

                for _ in range(self.scan_interval):
                    if self._shutdown_requested:
                        break
                    time.sleep(1)

                if self._shutdown_requested:
                    break

                # Run scan
                self.run_ingestion_scan()

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        finally:
            self._running = False
            logger.info("Scheduler stopped")

    def stop(self):
        """Request shutdown of the scheduler."""
        logger.info("Stopping scheduler...")
        self._shutdown_requested = True


def create_scheduler_from_env() -> AutoIngestionScheduler:
    """
    Create scheduler instance from environment configuration.

    Environment variables:
        AUTO_SCAN_INTERVAL: Seconds between scans (default: 300 = 5 minutes)
        AUTO_SCAN_INITIAL: Whether to run initial scan (default: true)
        AUTO_SCAN_INITIAL_WAIT: Seconds to wait before initial scan (default: 30)
        AUTO_SCAN_MAX_FILES: Max files to ingest per scan (default: 0 = no limit)

    Returns:
        Configured AutoIngestionScheduler instance
    """
    # Sync settings
    sync_settings_json()
    config = Config()

    # Get configuration from environment
    scan_interval = _config.AUTO_SCAN_INTERVAL
    initial_scan = _config.AUTO_SCAN_INITIAL
    initial_wait = _config.AUTO_SCAN_INITIAL_WAIT
    max_files = _config.AUTO_SCAN_MAX_FILES

    logger.info(f"Scheduler configuration:")
    logger.info(f"  Scan interval: {scan_interval}s ({scan_interval // 60} minutes)")
    logger.info(f"  Initial scan: {initial_scan}")
    logger.info(f"  Initial wait: {initial_wait}s")
    logger.info(f"  Max files per scan: {max_files if max_files else 'unlimited'}")

    return AutoIngestionScheduler(
        config=config,
        scan_interval=scan_interval,
        initial_scan=initial_scan,
        initial_wait=initial_wait,
        max_files=max_files,
    )


def main():
    """Main entry point for auto-scan scheduler."""
    # Configure logging
    log_level = os.environ.get("AUTO_SCAN_LOG_LEVEL", "INFO").upper()
    configure_logging(resolve_level(log_level))

    logger.info("=" * 60)
    logger.info("Auto-Scan Scheduler Starting")
    logger.info("=" * 60)
    logger.info("")
    logger.info("This scheduler uses Redis cache to efficiently detect")
    logger.info("changed files without watching the filesystem.")
    logger.info("")

    try:
        # Create and run scheduler
        scheduler = create_scheduler_from_env()
        scheduler.run_forever()

    except KeyboardInterrupt:
        logger.info("Shutdown requested")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        raise

    logger.info("")
    logger.info("=" * 60)
    logger.info("Auto-Scan Scheduler Stopped")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
