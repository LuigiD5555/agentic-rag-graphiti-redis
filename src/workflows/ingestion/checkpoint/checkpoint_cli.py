"""CLI for managing resumable checkpoint operations (SQLite-backed)."""

import argparse
import sys
from typing import Optional
from datetime import datetime

from src.workflows.query.audit import configure_logging, get_logger, resolve_level
from src.workflows.query.conf import sync_settings_json
import src.settings as settings
from src.backends.storage.sqlite.manager import get_sqlite_manager

log = get_logger(__name__)


class CheckpointCLI:
    """CLI for managing checkpoint operations."""

    def __init__(self):
        sync_settings_json()
        self._parser = self._build_parser()
        self._log = get_logger(__name__)
        self._sqlite_manager = get_sqlite_manager()

    def run(self):
        """Parse arguments and execute the appropriate command."""
        args = self._parser.parse_args()
        self._configure_logging(args.log_level)

        if args.command == "scan:list":
            self._list_scan_runs()
        elif args.command == "scan:resume":
            self._resume_scan(args.run_id)
        elif args.command == "scan:status":
            self._scan_status(args.run_id)
        elif args.command == "queue:stats":
            self._queue_stats()
        elif args.command == "queue:list":
            self._queue_list(args.limit)
        elif args.command == "queue:dlq":
            self._queue_dlq(args.limit)
        elif args.command == "queue:clear":
            self._queue_clear(args.force)
        elif args.command == "chunk:stats":
            self._chunk_stats()
        elif args.command == "chunk:file":
            self._chunk_file_status(args.file_id)
        else:
            self._parser.print_help()

    def _build_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(
            description="Manage resumable checkpoint operations"
        )

        parser.add_argument(
            "--log-level",
            default=None,
            help="Python log level (DEBUG, INFO, WARNING, ERROR).",
        )

        subparsers = parser.add_subparsers(dest="command", help="Command to execute")

        scan_list = subparsers.add_parser(
            "scan:list",
            help="List all active scan runs",
        )
        _ = scan_list

        scan_resume = subparsers.add_parser(
            "scan:resume",
            help="Resume an interrupted scan run",
        )
        scan_resume.add_argument("run_id", help="Run ID to resume")

        scan_status = subparsers.add_parser(
            "scan:status",
            help="Show detailed status of a scan run",
        )
        scan_status.add_argument("run_id", help="Run ID to check")

        queue_stats = subparsers.add_parser(
            "queue:stats",
            help="Show ingestion queue statistics",
        )
        _ = queue_stats

        queue_list = subparsers.add_parser(
            "queue:list",
            help="List pending jobs in queue",
        )
        queue_list.add_argument(
            "--limit",
            type=int,
            default=20,
            help="Maximum number of jobs to display",
        )

        queue_dlq = subparsers.add_parser(
            "queue:dlq",
            help="List jobs in dead letter queue (failed jobs)",
        )
        queue_dlq.add_argument(
            "--limit",
            type=int,
            default=20,
            help="Maximum number of jobs to display",
        )

        queue_clear = subparsers.add_parser(
            "queue:clear",
            help="Clear all queue data (DANGEROUS)",
        )
        queue_clear.add_argument(
            "--force",
            action="store_true",
            help="Skip confirmation prompt",
        )

        chunk_stats = subparsers.add_parser(
            "chunk:stats",
            help="Show chunk registry statistics",
        )
        _ = chunk_stats

        chunk_file = subparsers.add_parser(
            "chunk:file",
            help="Show chunk status for a specific file",
        )
        chunk_file.add_argument("file_id", help="File ID or path")

        return parser

    def _configure_logging(self, level_from_cli: Optional[str]) -> None:
        log_level_name = (
            level_from_cli
            or getattr(settings, "INGEST_LOG_LEVEL", "INFO")
            or "INFO"
        ).upper()
        level_value = resolve_level(log_level_name)
        configure_logging(level_value, fmt="%(levelname)s: %(message)s")

    # ============================================================================
    # Scan Commands
    # ============================================================================

    def _list_scan_runs(self):
        from src.workflows.ingestion.checkpoint.scan_checkpointer import ScanCheckpointer

        checkpointer = ScanCheckpointer()
        runs = checkpointer.list_runs()

        if not runs:
            print("No active scan runs found.")
            return

        print(f"\nActive Scan Runs ({len(runs)}):")
        print("-" * 80)

        for run in runs:
            created = datetime.fromtimestamp(run["created_at"]).strftime("%Y-%m-%d %H:%M:%S")
            print(f"Run ID: {run['run_id']}")
            print(f"  Status: {run['status']}")
            print(f"  Created: {created}")
            print(f"  Root Paths: {run.get('root_paths', 'N/A')}")
            print(f"  Files Found: {run.get('files_found', 0)}")
            print(f"  Directories Visited: {run.get('dirs_visited', 0)}")
            print()

    def _resume_scan(self, run_id: str):
        from src.workflows.ingestion.checkpoint.scan_checkpointer import ScanCheckpointer

        checkpointer = ScanCheckpointer()
        scan_run = checkpointer.resume_run(run_id)

        if not scan_run:
            print(f"ERROR: Cannot resume run '{run_id}' - not found or already completed")
            sys.exit(1)

        print(f"Resuming scan run: {run_id}")
        print(f"  Status: {scan_run.status}")
        print(f"  Files found so far: {scan_run.files_found}")
        print(f"  Directories pending: {len(scan_run.pending_dirs or [])}")
        print()

        print("Resume functionality requires orchestrator integration.")
        print("Use the run_id in your ingestion orchestrator to continue.")

    def _scan_status(self, run_id: str):
        from src.workflows.ingestion.checkpoint.scan_checkpointer import ScanCheckpointer

        checkpointer = ScanCheckpointer()
        scan_run = checkpointer.resume_run(run_id)

        if not scan_run:
            print(f"ERROR: Run '{run_id}' not found")
            sys.exit(1)

        print(f"\nScan Run Status: {run_id}")
        print("=" * 80)
        print(f"Status: {scan_run.status}")
        print(f"Created: {datetime.fromtimestamp(scan_run.started_at).strftime('%Y-%m-%d %H:%M:%S')}")

        print(f"\nRoot Paths: {', '.join(scan_run.root_paths)}")
        print(f"Options Hash: {scan_run.options_hash}")

        print(f"\nProgress:")
        print(f"  Files Found: {scan_run.files_found}")
        print(f"  Directories Visited: {len(checkpointer.get_visited_directories(run_id))}")
        print(f"  Directories Pending: {len(scan_run.pending_dirs or [])}")

    # ============================================================================
    # Queue Commands
    # ============================================================================

    def _queue_stats(self):
        from src.workflows.ingestion.checkpoint.ingest_queue import IngestQueue

        queue = IngestQueue()
        stats = queue.get_stats()

        print("\nIngestion Queue Statistics:")
        print("=" * 80)
        print(f"Total Enqueued: {stats['total_enqueued']}")
        print(f"Pending: {stats['pending']}")
        print(f"Processing: {stats['processing']}")
        print(f"Completed: {stats['completed']}")
        print(f"Failed: {stats['failed']}")
        print()
        print(f"Queue Length: {queue.get_queue_length()}")
        print(f"DLQ Length: {queue.get_dlq_length()}")

        consumers = queue.list_consumers()
        if consumers:
            print(f"\nActive Consumers ({len(consumers)}):")
            for consumer in consumers:
                last_seen = datetime.fromtimestamp(consumer["last_seen"]).strftime("%Y-%m-%d %H:%M:%S")
                print(f"  {consumer['name']} (last seen: {last_seen})")

    def _queue_list(self, limit: int):
        conn = self._sqlite_manager.control_plane.get_connection()
        cursor = conn.execute(
            """
            SELECT job_id, file_path, run_id, retry_count, enqueued_at
            FROM ingest_jobs
            WHERE status = 'pending'
            ORDER BY enqueued_at ASC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            print("No pending jobs in queue.")
            return

        print(f"\nPending Jobs (showing {len(rows)}):")
        print("=" * 80)

        for row in rows:
            print(f"Job ID: {row[0]}")
            print(f"  File: {row[1]}")
            print(f"  Run ID: {row[2]}")
            print(f"  Retry Count: {row[3]}")
            enqueued_at = float(row[4] or 0)
            if enqueued_at:
                print(f"  Enqueued: {datetime.fromtimestamp(enqueued_at).strftime('%Y-%m-%d %H:%M:%S')}")
            print()

    def _queue_dlq(self, limit: int):
        conn = self._sqlite_manager.control_plane.get_connection()
        cursor = conn.execute(
            """
            SELECT job_id, file_path, run_id, retry_count, error, completed_at
            FROM ingest_jobs
            WHERE status = 'dlq'
            ORDER BY completed_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            print("Dead letter queue is empty.")
            return

        print(f"\nDead Letter Queue (showing {len(rows)}):")
        print("=" * 80)

        for row in rows:
            print(f"Job ID: {row[0]}")
            print(f"  File: {row[1]}")
            print(f"  Run ID: {row[2]}")
            print(f"  Retry Count: {row[3]}")
            print(f"  Error: {row[4] or 'Unknown'}")
            failed_at = float(row[5] or 0)
            if failed_at:
                print(f"  Failed: {datetime.fromtimestamp(failed_at).strftime('%Y-%m-%d %H:%M:%S')}")
            print()

    def _queue_clear(self, force: bool):
        from src.workflows.ingestion.checkpoint.ingest_queue import IngestQueue

        if not force:
            response = input("Are you sure you want to clear ALL queue data? This cannot be undone. [y/N]: ")
            if response.lower() != "y":
                print("Aborted.")
                return

        queue = IngestQueue()
        queue.clear_queue()
        print("Queue data cleared successfully.")

    # ============================================================================
    # Chunk Commands
    # ============================================================================

    def _chunk_stats(self):
        from src.workflows.ingestion.checkpoint.chunk_registry import ChunkRegistry

        registry = ChunkRegistry()
        stats = registry.get_stats()

        print("\nChunk Registry Statistics:")
        print("=" * 80)
        print(f"Total Chunks: {stats['total_chunks']}")
        print(f"Pending: {stats['status_pending']}")
        print(f"Processing: {stats['status_processing']}")
        print(f"Completed: {stats['status_completed']}")
        print(f"Failed: {stats['status_failed']}")

        if stats["total_chunks"] > 0:
            completed_pct = (stats["status_completed"] / stats["total_chunks"]) * 100
            print(f"\nCompletion: {completed_pct:.1f}%")

    def _chunk_file_status(self, file_id: str):
        from src.workflows.ingestion.checkpoint.chunk_registry import ChunkRegistry

        registry = ChunkRegistry()
        chunks = registry.get_file_chunks(file_id)

        if not chunks:
            print(f"No chunks found for file: {file_id}")
            return

        progress = registry.get_file_progress(file_id)

        print(f"\nChunk Status for File: {file_id}")
        print("=" * 80)
        print(f"Total Chunks: {progress['total']}")
        print(f"Pending: {progress['pending']}")
        print(f"Processing: {progress['processing']}")
        print(f"Completed: {progress['completed']}")
        print(f"Failed: {progress['failed']}")
        print(f"Progress: {progress['progress_pct']:.1f}%")

        print(f"\nChunk Details (showing {min(len(chunks), 20)} of {len(chunks)}):")
        for i, (chunk_id, status) in enumerate(list(chunks.items())[:20], 1):
            meta = registry.get_chunk_metadata(chunk_id)
            print(f"{i}. {chunk_id[:16]}... - {status.value}")
            if meta and meta.last_error:
                print(f"   Error: {meta.last_error}")


def main():
    """Entry point for checkpoint CLI."""
    CheckpointCLI().run()


__all__ = ["CheckpointCLI", "main"]


if __name__ == "__main__":
    main()
