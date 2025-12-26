#!/usr/bin/env python3
"""
Alert Notification Script for Systemd Service Failures

This script is triggered by systemd OnFailure hooks when a tool service fails.
It logs the failure and can send notifications via multiple channels.

Usage:
    Called automatically by systemd when a service fails:
    ExecStart=/usr/bin/python3 /path/to/alert_notify.py %n

Environment variables (set by systemd):
    - UNIT_NAME: Name of the failed unit
    - RESULT: Result of the unit execution
"""

import sys
import subprocess
from datetime import datetime
from pathlib import Path
import json


class AlertNotifier:
    """Handles notifications for service failures."""

    def __init__(self, unit_name: str):
        """
        Initialize notifier.

        Args:
            unit_name: Name of the failed systemd unit
        """
        self.unit_name = unit_name
        self.project_root = Path(__file__).parent.parent.parent
        self.log_dir = self.project_root / 'logs' / 'alerts'
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def get_service_status(self) -> dict:
        """
        Get detailed status of the failed service.

        Returns:
            Dictionary with service status information
        """
        try:
            result = subprocess.run(
                ['systemctl', '--user', 'status', self.unit_name, '--no-pager'],
                capture_output=True,
                text=True,
                timeout=5
            )

            return {
                'status_output': result.stdout,
                'exit_code': result.returncode
            }
        except Exception as e:
            return {
                'status_output': f'Failed to get status: {e}',
                'exit_code': -1
            }

    def get_recent_logs(self, lines: int = 50) -> str:
        """
        Get recent logs from the failed service.

        Args:
            lines: Number of log lines to retrieve

        Returns:
            Recent log output
        """
        try:
            result = subprocess.run(
                ['journalctl', '--user', '-u', self.unit_name, '-n', str(lines), '--no-pager'],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.stdout
        except Exception as e:
            return f'Failed to get logs: {e}'

    def log_failure(self) -> Path:
        """
        Log the failure to a file.

        Returns:
            Path to the log file
        """
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        log_file = self.log_dir / f'{self.unit_name}_{timestamp}.log'

        status = self.get_service_status()
        logs = self.get_recent_logs()

        with open(log_file, 'w') as f:
            f.write(f"=== Service Failure Alert ===\n")
            f.write(f"Unit: {self.unit_name}\n")
            f.write(f"Time: {datetime.now().isoformat()}\n")
            f.write(f"\n=== Service Status ===\n")
            f.write(status['status_output'])
            f.write(f"\n=== Recent Logs (last 50 lines) ===\n")
            f.write(logs)

        return log_file

    def send_desktop_notification(self, message: str):
        """
        Send desktop notification (if notify-send is available).

        Args:
            message: Notification message
        """
        try:
            subprocess.run(
                ['notify-send',
                 '-u', 'critical',
                 '-i', 'dialog-error',
                 'RAG Tool Service Failed',
                 message],
                timeout=2,
                check=False
            )
        except Exception:
            pass  # Desktop notifications are optional

    def send_systemd_wall(self, message: str):
        """
        Send wall message to all logged-in users.

        Args:
            message: Message to broadcast
        """
        try:
            subprocess.run(
                ['wall', message],
                timeout=2,
                check=False
            )
        except Exception:
            pass  # Wall is optional

    def notify(self):
        """
        Execute notification workflow.

        1. Log failure details to file
        2. Send desktop notification (if available)
        3. Print to stderr for systemd journal
        """
        # Log to file
        log_file = self.log_failure()

        # Prepare message
        tool_name = self.unit_name.replace('tool-', '').replace('.service', '')
        message = (
            f"RAG Tool '{tool_name}' has failed!\n"
            f"Check logs: {log_file}\n"
            f"Or run: python -m src.tools.systemd_manager logs {tool_name} -p err"
        )

        # Send desktop notification
        self.send_desktop_notification(message)

        # Print to stderr (captured by systemd journal)
        print(f"\n{'='*70}", file=sys.stderr)
        print(f"⚠️  ALERT: Service Failure Detected", file=sys.stderr)
        print(f"{'='*70}", file=sys.stderr)
        print(message, file=sys.stderr)
        print(f"{'='*70}\n", file=sys.stderr)

        # Return success
        return 0


def main():
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: alert_notify.py <unit-name>", file=sys.stderr)
        sys.exit(1)

    unit_name = sys.argv[1]

    # Skip non-tool services
    if not unit_name.startswith('tool-'):
        sys.exit(0)

    notifier = AlertNotifier(unit_name)
    sys.exit(notifier.notify())


if __name__ == '__main__':
    main()
