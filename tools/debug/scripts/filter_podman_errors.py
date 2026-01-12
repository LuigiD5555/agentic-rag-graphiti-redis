#!/usr/bin/env python3
"""Filter podman logs for errors/warnings and keep daily archives."""
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
    base_cmd = ["podman", "logs", container]

    def _exec(cmd: list[str]) -> subprocess.CompletedProcess:
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
    return [line for line in text.splitlines() if pattern.search(line)]


def write_output(out_dir: Path, container: str, lines: list[str]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"{container}_errors_{timestamp}.log"
    out_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return out_path


def prune_old_logs(out_dir: Path, retention_hours: int) -> None:
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
    cmd = ["podman", "ps", "--format", "{{.Names}}"]
    if include_stopped:
        cmd.insert(2, "-a")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def podman_supports_since() -> bool:
    proc = subprocess.run(
        ["podman", "logs", "--help"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return False
    return "--since" in proc.stdout


def get_container_started_at(container: str) -> str | None:
    cmd = ["podman", "inspect", "--format", "{{.State.StartedAt}}", container]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    started_at = proc.stdout.strip()
    return started_at or None


def main() -> None:
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
            matches = matches[-args.limit :]

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
