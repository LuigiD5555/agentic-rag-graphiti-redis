"""
Auto-Ingestion Scheduler - Periodically scans directories and triggers ingestion for changed files.

This service runs in the background and periodically executes the ingestion scanner,
which uses SQLite control plane to efficiently detect only files that have changed (based on
mtime, size, and optionally content hash).

This approach is more efficient than file system watchers because:
- Reuses existing SQLite control plane infrastructure
- Scales better with large directories
- More reliable (no missed events)
- Lower resource usage (no inotify watchers)
- Handles batch changes efficiently

How it works:
1. Scanner reads file metadata from SQLite control plane
2. Compares current mtime/size with stored values
3. Only processes files that changed
4. Updates SQLite after successful ingestion
"""

"""Auto-scan scheduler for periodic ingestion scans."""
import argparse
import asyncio
import time
from datetime import datetime

from src.backends.storage.sqlite.manager import get_sqlite_manager
from src.conf import settings as runtime_settings
from src.workflows.ingestion.helpers import build_ingestion_options_from_args
from src.workflows.ingestion.orchestrator import IngestionOrchestrator
from src.workflows.query.audit import get_logger

logger = get_logger(__name__)


class AutoScanScheduler:
    """Scheduler that periodically scans for changed files and triggers ingestion."""

    def __init__(self, config: object) -> None:
        """
        Initialize scheduler with configuration.

        Args:
            config: Runtime settings object.
        """
        self.config = config
        self.orchestrator = IngestionOrchestrator(config)
        
        # Get SQLite control plane manager
        self.sqlite_manager = get_sqlite_manager()
        self.scan_checkpoint_store = self.sqlite_manager.get_scan_checkpoint_store()
        self.file_metadata_store = self.sqlite_manager.get_file_metadata_store()

        # Scheduler configuration
        self.scan_interval = getattr(config, "AUTO_SCAN_INTERVAL", 300)
        self.initial_scan = getattr(config, "AUTO_SCAN_INITIAL", True)
        self.initial_wait = getattr(config, "AUTO_SCAN_INITIAL_WAIT", 30)
        self.max_files_per_scan = getattr(config, "AUTO_SCAN_MAX_FILES", None)

    async def run(self) -> None:
        """Run the scheduler loop indefinitely."""
        logger.info("=" * 60)
        logger.info("Auto-Scan Scheduler Starting")
        logger.info("=" * 60)
        logger.info("")
        logger.info("This scheduler uses SQLite control plane to efficiently detect")
        logger.info("changed files without watching the filesystem.")
        logger.info("")
        logger.info("Scheduler configuration:")
        logger.info(f"  Scan interval: {self.scan_interval}s ({self.scan_interval/60:.1f} minutes)")
        logger.info(f"  Initial scan: {self.initial_scan}")
        logger.info(f"  Initial wait: {self.initial_wait}s")
        logger.info(f"  Max files per scan: {self.max_files_per_scan or 'unlimited'}")
        logger.info("=" * 60)

        # Wait for initial delay
        if self.initial_wait > 0:
            logger.info(f"Waiting {self.initial_wait}s before first scan...")
            await asyncio.sleep(self.initial_wait)

        # Perform initial scan if enabled
        if self.initial_scan:
            await self.run_ingestion_scan(full_scan=True)

        # Main scheduler loop
        logger.info("")
        logger.info("=" * 60)
        logger.info(f"Starting periodic scanning (every {self.scan_interval}s)")
        logger.info("=" * 60)

        while True:
            try:
                await asyncio.sleep(self.scan_interval)
                await self.run_ingestion_scan(full_scan=False)
            except Exception as e:
                logger.error(f"Scheduler loop error: {e}", exc_info=True)
                # Continue running despite errors

    async def run_ingestion_scan(self, full_scan: bool = False) -> None:
        """
        Run an ingestion scan.

        Args:
            full_scan: If True, run a full scan. If False, run incremental scan.
        """
        scan_type = "FULL" if full_scan else "INCREMENTAL"
        logger.info("")
        logger.info("-" * 60)
        logger.info(f"Starting {scan_type} scan at {datetime.now().isoformat()}")
        logger.info("-" * 60)

        # Build options
        parser = self._create_arg_parser()
        args = parser.parse_args([])  # No CLI args for scheduler
        options = build_ingestion_options_from_args(args, self.config)

        try:
            if full_scan:
                result = self.orchestrator.run_with_report(options)
            else:
                result = self.orchestrator.run_incremental_scan(options)

            status = result.get("status", "unknown")
            processed = result.get("pipeline", {}).get("processed_files", 0)

            logger.info(f"Scan completed: status={status}, processed_files={processed}")

        except Exception as e:
            logger.error(f"Scan failed: {e}", exc_info=True)

    def _create_arg_parser(self) -> argparse.ArgumentParser:
        """
        Create argument parser for ingestion options.

        Returns:
            argparse.ArgumentParser instance.
        """
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--paths", nargs="*")
        parser.add_argument("--exts", nargs="*")
        parser.add_argument("--exclude-dirs", nargs="*")
        parser.add_argument("--exclude-patterns", nargs="*")
        parser.add_argument("--enabled-paths", nargs="*")
        parser.add_argument("--follow-symlinks", action="store_true")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--per-file", action="store_true")
        parser.add_argument("--max-files", type=int)
        parser.add_argument("--streaming", action="store_true")
        parser.add_argument("--log-level")
        parser.add_argument("--scan-progress", type=int)
        return parser


async def main() -> None:
    """Entry point for running the scheduler."""
    scheduler = AutoScanScheduler(runtime_settings)
    await scheduler.run()


def check_health() -> bool:
    """
    Health check function for container healthchecks.
    
    Returns:
        True if the scheduler is healthy, False otherwise.
    """
    try:
        # Check if SQLite control plane is accessible
        sqlite_manager = get_sqlite_manager()
        
        # Test SQLite connection by checking if we can query the database
        with sqlite_manager.control_plane.get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'")
            table_count = cursor.fetchone()[0]
            
            if table_count == 0:
                logger.error("SQLite control plane has no tables")
                return False
        
        # Update last heartbeat in SQLite
        with sqlite_manager.control_plane.get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO audit_events 
                (event_id, session_id, event_type, event_at, metadata_json)
                VALUES (?, ?, ?, ?, ?)
            """, (
                f"heartbeat_{int(time.time())}",
                "autoscan",
                "HEARTBEAT",
                int(time.time()),
                '{"service": "autoscan"}'
            ))
        
        logger.debug("Health check passed")
        return True
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return False


if __name__ == "__main__":
    asyncio.run(main())