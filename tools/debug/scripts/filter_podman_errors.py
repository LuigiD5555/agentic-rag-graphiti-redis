#!/usr/bin/env python3
"""Filter podman logs for errors/warnings and keep daily archives.

Usage examples:
    # Filter logs from default container
    python filter_podman_errors.py
    
    # Filter from specific container
    python filter_podman_errors.py --container my_container
    
    # Filter from multiple containers
    python filter_podman_errors.py --containers "app1,app2,app3"
    
    # Filter from all running containers
    python filter_podman_errors.py --all-containers
    
    # Filter with custom pattern
    python filter_podman_errors.py --pattern "(error|fail|exception)"
    
    # Keep logs for 7 days
    python filter_podman_errors.py --retention-hours 168
    
    # Get full session logs (since container start)
    python filter_podman_errors.py --full-session
    
Output:
    - Creates timestamped log files in tools/debug/logs/filtered/
    - Creates consolidated errors_all.txt and warnings_all.txt
    - Automatically prunes old logs based on retention period
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
from pathlib import Path


DEFAULT_PATTERN = r"(ERROR|WARNING|Error|Warning|failed|Failed)"
ERROR_PATTERN = re.compile(r"(ERROR|Error|Failed|failed|Exception|Traceback)")
WARNING_PATTERN = re.compile(r"(WARNING|Warning)")


def parse_args() -> argparse.Namespace:
    """Parse command line arguments.
    
    Returns:
        argparse.Namespace: Parsed command line arguments.
        
    Options:
        --container: Single container name to process
        --containers: Comma-separated list of container names
        --all-containers: Process all running containers
        --all-containers-include-stopped: Process all containers including stopped ones
        --tail: Number of log lines to read (default: 200)
        --pattern: Regex pattern for filtering (default: matches ERROR/WARNING/failed)
        --limit: Maximum filtered lines to keep (0 = no limit)
        --out-dir: Output directory for filtered logs
        --retention-hours: Delete logs older than this many hours
        --full-session: Use container start time as log start
        --since-hours: Look back this many hours if not using full session
    """
    parser = argparse.ArgumentParser(
        description="Filter podman logs for errors/warnings and store results for 1 day."
    )
    parser.add_argument(
        "--container",
        default="rag-graphiti-agentic_autoscan_1",
        help="Podman container name (default: rag-graphiti-agentic_autoscan_1)",
    )
    parser.add_argument(
        "--containers",
        help="Comma-separated container names to process (overrides --container)",
    )
    parser.add_argument(
        "--all-containers",
        action="store_true",
        help="Process all running containers",
    )
    parser.add_argument(
        "--all-containers-include-stopped",
        action="store_true",
        help="Process all containers, including stopped ones",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=200,
        help="Number of log lines to read from podman (default: 200)",
    )
    parser.add_argument(
        "--pattern",
        default=DEFAULT_PATTERN,
        help=f"Regex pattern for filtering (default: {DEFAULT_PATTERN})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max filtered lines to keep (default: 50, use 0 for no limit)",
    )
    parser.add_argument(
        "--out-dir",
        default="tools/debug/logs/filtered",
        help="Output directory for filtered logs",
    )
    parser.add_argument(
        "--retention-hours",
        type=int,
        default=24,
        help="Delete log files older than this many hours (default: 24)",
    )
    parser.add_argument(
        "--full-session",
        action="store_true",
        help="Use container start time as log start (captures full session)",
    )
    parser.add_argument(
        "--since-hours",
        type=int,
        default=24,
        help="If not using full session, look back this many hours (default: 24)",
    )
    return parser.parse_args()


def run_podman_logs(container: str, tail: int | None, since: str | None) -> str:
    """Run podman logs command and return output.
    
    Args:
        container: Container name to get logs from.
        tail: Number of lines to tail from the end (None for all).
        since: Time duration to look back (e.g., "24h").
        
    Returns:
        str: Combined stdout and stderr from podman logs command.
        
    Note:
        Handles compatibility with older podman versions that may not
        support --since flag by falling back to --tail or no flags.
    """
    base_cmd = ["podman", "logs", container]

    def _exec(cmd: list[str]) -> subprocess.CompletedProcess:
        """Execute command and return CompletedProcess."""
        proc = subprocess.run(cmd, capture_output=True, text=True)
        return proc

    cmd = list(base_cmd)
    if since:
        cmd[1:1] = ["--since", since]
    elif tail is not None:
        cmd[1:1] = ["--tail", str(tail)]

    proc = _exec(cmd)
    stderr = proc.stderr or ""
    if proc.returncode != 0 and since and "unknown flag" in stderr:
        fallback_cmd = list(base_cmd)
        if tail is not None:
            fallback_cmd[1:1] = ["--tail", str(tail)]
        proc = _exec(fallback_cmd)
    stderr = proc.stderr or ""
    if proc.returncode != 0 and "unknown flag" in stderr and "--tail" in stderr:
        # Retry without the unsupported flag
        proc = _exec(base_cmd)
    return proc.stdout + proc.stderr


def filter_lines(text: str, pattern: re.Pattern[str]) -> list[str]:
    """Filter lines matching regex pattern.
    
    Args:
        text: Multiline text to filter.
        pattern: Compiled regex pattern to search for.
        
    Returns:
        list[str]: List of lines containing the pattern.
    """
    return [line for line in text.splitlines() if pattern.search(line)]


def write_output(out_dir: Path, container: str, lines: list[str]) -> Path:
    """Write filtered lines to timestamped log file.
    
    Args:
        out_dir: Directory to write output file.
        container: Container name for filename.
        lines: List of filtered log lines.
        
    Returns:
        Path: Path to created log file.
        
    Note:
        Creates directory if it doesn't exist. Filename format:
        {container}_errors_{timestamp}.log
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"{container}_errors_{timestamp}.log"
    out_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return out_path


def prune_old_logs(out_dir: Path, retention_hours: int) -> None:
    """Delete log files older than retention period.
    
    Args:
        out_dir: Directory containing log files.
        retention_hours: Maximum age in hours to keep files.
        
    Note:
        Silently skips files that can't be read or deleted.
    """
    cutoff = dt.datetime.now() - dt.timedelta(hours=retention_hours)
    for path in out_dir.glob("*.log"):
        try:
            mtime = dt.datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            continue
        if mtime < cutoff:
            try:
                path.unlink()
            except OSError:
                continue


def list_containers(include_stopped: bool) -> list[str]:
    """List podman containers.
    
    Args:
        include_stopped: If True, include stopped containers in the list.
        
    Returns:
        list[str]: List of container names.
        
    Example:
        >>> list_containers(False)
        ['container1', 'container2']
        >>> list_containers(True)
        ['container1', 'container2', 'stopped_container']
    """
    cmd = ["podman", "ps", "--format", "{{.Names}}"]
    if include_stopped:
        cmd.insert(2, "-a")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def podman_supports_since() -> bool:
    """Check if podman supports --since flag for logs command.
    
    Returns:
        bool: True if podman supports --since flag, False otherwise.
        
    Note:
        This is important for compatibility with older podman versions
        that may not support the --since flag for filtering logs by time.
        
    Example:
        >>> podman_supports_since()
        True  # On modern podman versions
    """
    proc = subprocess.run(
        ["podman", "logs", "--help"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return False
    return "--since" in proc.stdout


def get_container_started_at(container: str) -> str | None:
    """Get container start time using podman inspect.
    
    Args:
        container: Container name to inspect.
        
    Returns:
        str | None: Container start time as string, or None if not found.
        
    Example:
        >>> get_container_started_at("my_container")
        "2024-01-19T09:30:00.123456789Z"
    """
    cmd = ["podman", "inspect", "--format", "{{.State.StartedAt}}", container]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    started_at = proc.stdout.strip()
    return started_at or None


def main() -> None:
    """Main entry point for filtering podman logs.
    
    Workflow:
        1. Parse command line arguments
        2. Determine which containers to process
        3. For each container:
           - Get logs using appropriate method (--since, --tail, or full session)
           - Filter lines matching pattern
           - Apply limit if specified
           - Write filtered logs to timestamped file
           - Categorize errors and warnings for consolidated output
        4. Prune old log files based on retention period
        5. Write consolidated error and warning files
        
    Raises:
        SystemExit: If no containers are found to process.
        
    Outputs:
        - Individual timestamped log files per container
        - Consolidated errors_all.txt with all errors across containers
        - Consolidated warnings_all.txt with all warnings across containers
    """
    args = parse_args()
    out_dir = Path(args.out_dir)
    pattern = re.compile(args.pattern)
    supports_since = podman_supports_since()
    combined_errors: list[str] = []
    combined_warnings: list[str] = []

    if args.containers:
        containers = [name.strip() for name in args.containers.split(",") if name.strip()]
    elif args.all_containers or args.all_containers_include_stopped:
        containers = list_containers(args.all_containers_include_stopped)
    else:
        containers = [args.container]

    if not containers:
        raise SystemExit("No containers found to process.")

    for container in containers:
        since_value = None
        tail_value: int | None = args.tail
        if args.full_session:
            if supports_since:
                since_value = get_container_started_at(container)
            else:
                tail_value = None
        elif supports_since:
            since_value = f"{args.since_hours}h"

        raw_logs = run_podman_logs(container, tail_value, since_value)
        matches = filter_lines(raw_logs, pattern)

        if args.limit and args.limit > 0 and len(matches) > args.limit:
            matches = matches[-args.limit:]

        out_path = write_output(out_dir, container, matches)
        print(f"Wrote {len(matches)} lines to {out_path}")
        for line in matches:
            if ERROR_PATTERN.search(line):
                combined_errors.append(f"[{container}] {line}")
            elif WARNING_PATTERN.search(line):
                combined_warnings.append(f"[{container}] {line}")

    prune_old_logs(out_dir, args.retention_hours)

    if combined_errors:
        (out_dir / "errors_all.txt").write_text(
            "\n".join(combined_errors) + "\n", encoding="utf-8"
        )
    if combined_warnings:
        (out_dir / "warnings_all.txt").write_text(
            "\n".join(combined_warnings) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
