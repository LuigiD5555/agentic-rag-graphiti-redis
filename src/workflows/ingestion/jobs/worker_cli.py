"""CLI for starting RabbitMQ ingestion workers."""

import argparse
import asyncio
import signal
import sys
from typing import Optional

from src.workflows.query.audit import get_logger
from .worker import start_worker_cluster

log = get_logger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="RabbitMQ Ingestion Worker CLI")
    
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # Start command
    start_parser = subparsers.add_parser("start", help="Start worker cluster")
    start_parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of workers to start (default: 1)"
    )
    start_parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Concurrency per worker (default: 4)"
    )
    start_parser.add_argument(
        "--max-retries",
        type=int,
        default=3,
        help="Maximum retry attempts (default: 3)"
    )
    
    # Status command
    subparsers.add_parser("status", help="Check worker status")
    
    # Stop command
    subparsers.add_parser("stop", help="Stop workers")
    
    return parser.parse_args()


async def start_workers(args: argparse.Namespace) -> None:
    """Start worker cluster."""
    log.info(
        "Starting ingestion worker cluster with %d workers, %d concurrency, %d max retries",
        args.workers,
        args.concurrency,
        args.max_retries
    )
    
    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    
    def signal_handler():
        log.info("Received shutdown signal")
        stop_event.set()
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)
    
    try:
        # Start worker cluster
        worker_task = asyncio.create_task(
            start_worker_cluster(
                worker_count=args.workers,
                concurrency_per_worker=args.concurrency,
                max_retries=args.max_retries
            )
        )
        
        # Create a task for the stop event
        stop_task = asyncio.create_task(stop_event.wait())
        
        # Wait for stop event or worker task completion
        done, pending = await asyncio.wait(
            [worker_task, stop_task],
            return_when=asyncio.FIRST_COMPLETED
        )
        
        # Cancel worker task if still running
        if not worker_task.done():
            worker_task.cancel()
            try:
                await worker_task
            except asyncio.CancelledError:
                pass
        
        log.info("Worker cluster stopped gracefully")
        
    except Exception as e:
        log.error("Error in worker cluster: %s", e)
        raise


def check_status() -> None:
    """Check worker status."""
    # TODO: Implement status checking
    # This could check RabbitMQ queue status, worker processes, etc.
    log.info("Status check not yet implemented")
    print("Worker status: Not implemented yet")


def stop_workers() -> None:
    """Stop workers."""
    # TODO: Implement worker stopping
    # This could send signals to worker processes
    log.info("Stop command not yet implemented")
    print("Stop command: Not implemented yet")


async def async_main() -> None:
    """Async main function."""
    args = parse_args()
    
    if args.command == "start":
        await start_workers(args)
    elif args.command == "status":
        check_status()
    elif args.command == "stop":
        stop_workers()
    else:
        print("Please specify a command: start, status, or stop")
        sys.exit(1)


def main() -> None:
    """Main entry point."""
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        log.info("CLI interrupted by user")
        sys.exit(0)
    except Exception as e:
        log.error("CLI error: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()