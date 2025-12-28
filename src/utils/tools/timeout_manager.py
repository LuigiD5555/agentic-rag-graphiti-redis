#!/usr/bin/env python3
"""
Tool Timeout Manager

Manages auto-shutdown timeouts for socket-activated RAG tools.
Reads timeout values from data/settings.json and regenerates systemd service files.

Usage:
    python -m src.utils.tools.timeout_manager show              # Show current timeouts
    python -m src.utils.tools.timeout_manager set office 900    # Set office timeout to 15 minutes
    python -m src.utils.tools.timeout_manager set all 1200      # Set all tools to 20 minutes
    python -m src.utils.tools.timeout_manager apply             # Apply changes to systemd
"""

import sys
import json
import os
from pathlib import Path
from typing import Dict, Optional
import shutil


class Colors:
    """ANSI color codes for terminal output."""
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    BOLD = '\033[1m'
    NC = '\033[0m'  # No Color


class TimeoutManager:
    """Manages timeout configuration for RAG tools."""

    TOOLS = ['office', 'archive', 'ocr', 'gpu']
    DEFAULT_TIMEOUT = 600  # 10 minutes

    def __init__(self):
        """Initialize timeout manager."""
        self.project_root = Path(__file__).parent.parent.parent.parent
        self.settings_file = self.project_root / 'data' / 'settings.json'
        self.systemd_dir = self.project_root / 'systemd' / 'user'
        self.user_systemd_dir = Path.home() / '.config' / 'systemd' / 'user'

    def load_settings(self) -> Dict:
        """
        Load settings from data/settings.json.

        Returns:
            Dictionary with settings
        """
        if not self.settings_file.exists():
            return {}

        with open(self.settings_file, 'r') as f:
            return json.load(f)

    def save_settings(self, settings: Dict):
        """
        Save settings to data/settings.json.

        Args:
            settings: Dictionary with settings
        """
        self.settings_file.parent.mkdir(parents=True, exist_ok=True)

        with open(self.settings_file, 'w') as f:
            json.dump(settings, f, indent=2)

    def get_timeouts(self) -> Dict[str, int]:
        """
        Get current timeout values.

        Returns:
            Dictionary mapping tool names to timeout values (seconds)
        """
        settings = self.load_settings()
        timeouts = settings.get('TOOL_IDLE_TIMEOUTS', {})

        # Fill in defaults for missing tools
        for tool in self.TOOLS:
            if tool not in timeouts:
                timeouts[tool] = self.DEFAULT_TIMEOUT

        return timeouts

    def set_timeout(self, tool: str, timeout: int, verbose: bool = True) -> bool:
        """
        Set timeout for a specific tool or all tools.

        Args:
            tool: Tool name ('office', 'archive', 'ocr', 'gpu', or 'all')
            timeout: Timeout value in seconds (0 to disable)
            verbose: Print status messages

        Returns:
            True if successful, False otherwise
        """
        if tool != 'all' and tool not in self.TOOLS:
            if verbose:
                print(f"{Colors.RED}✗ Invalid tool:{Colors.NC} {tool}")
                print(f"  Valid tools: {', '.join(self.TOOLS)} or 'all'")
            return False

        if timeout < 0:
            if verbose:
                print(f"{Colors.RED}✗ Invalid timeout:{Colors.NC} {timeout}")
                print(f"  Timeout must be >= 0 (0 = disabled)")
            return False

        # Load settings
        settings = self.load_settings()
        if 'TOOL_IDLE_TIMEOUTS' not in settings:
            settings['TOOL_IDLE_TIMEOUTS'] = {}

        # Update timeout(s)
        if tool == 'all':
            for t in self.TOOLS:
                settings['TOOL_IDLE_TIMEOUTS'][t] = timeout
            if verbose:
                print(f"{Colors.GREEN}✓ Set all tools to {timeout}s{Colors.NC}")
        else:
            settings['TOOL_IDLE_TIMEOUTS'][tool] = timeout
            if verbose:
                print(f"{Colors.GREEN}✓ Set {tool} to {timeout}s{Colors.NC}")

        # Save settings
        self.save_settings(settings)

        if verbose:
            print(f"\n{Colors.YELLOW}⚠ Changes saved to settings.json{Colors.NC}")
            print(f"Run {Colors.CYAN}python -m src.utils.tools.timeout_manager apply{Colors.NC} to update systemd services")

        return True

    def show_timeouts(self, verbose: bool = True):
        """
        Display current timeout configuration.

        Args:
            verbose: Print formatted output
        """
        timeouts = self.get_timeouts()

        if verbose:
            print(f"{Colors.BLUE}{'='*70}{Colors.NC}")
            print(f"{Colors.BOLD}Tool Auto-Shutdown Timeouts{Colors.NC}")
            print(f"{Colors.BLUE}{'='*70}{Colors.NC}\n")

            print(f"{'Tool':<12} {'Timeout (sec)':<15} {'Human Readable':<20}")
            print(f"{'-'*50}")

            for tool in self.TOOLS:
                timeout = timeouts.get(tool, self.DEFAULT_TIMEOUT)
                human = self._format_timeout(timeout)
                color = Colors.GREEN if timeout > 0 else Colors.YELLOW

                print(f"{tool:<12} {color}{timeout:<15}{Colors.NC} {human}")

            print(f"\n{Colors.CYAN}Note:{Colors.NC} Set timeout to 0 to disable auto-shutdown")
            print(f"{Colors.CYAN}Location:{Colors.NC} {self.settings_file}")
            print()

        return timeouts

    def apply_timeouts(self, verbose: bool = True) -> bool:
        """
        Apply timeout settings to systemd service files.

        Regenerates service files with current timeout values and
        installs them to user systemd directory.

        Args:
            verbose: Print status messages

        Returns:
            True if successful, False otherwise
        """
        timeouts = self.get_timeouts()

        if verbose:
            print(f"{Colors.BLUE}{'='*70}{Colors.NC}")
            print(f"{Colors.BOLD}Applying Timeout Configuration{Colors.NC}")
            print(f"{Colors.BLUE}{'='*70}{Colors.NC}\n")

        success = True

        for tool in self.TOOLS:
            timeout = timeouts.get(tool, self.DEFAULT_TIMEOUT)
            service_file = self.systemd_dir / f'tool-{tool}.service'

            if not service_file.exists():
                if verbose:
                    print(f"{Colors.YELLOW}⚠ Skipping:{Colors.NC} {service_file} not found")
                continue

            # Update RuntimeMaxSec in service file
            if not self._update_service_file(service_file, timeout):
                if verbose:
                    print(f"{Colors.RED}✗ Failed to update {service_file}{Colors.NC}")
                success = False
                continue

            # Copy to user systemd directory
            if self.user_systemd_dir.exists():
                shutil.copy2(service_file, self.user_systemd_dir)
                if verbose:
                    print(f"{Colors.GREEN}✓ Updated tool-{tool}.service{Colors.NC} (timeout: {timeout}s)")
            else:
                if verbose:
                    print(f"{Colors.YELLOW}⚠ User systemd dir not found:{Colors.NC} {self.user_systemd_dir}")

        if verbose:
            print(f"\n{Colors.CYAN}Next steps:{Colors.NC}")
            print(f"  1. Reload systemd: {Colors.BOLD}systemctl --user daemon-reload{Colors.NC}")
            print(f"  2. Restart tools: {Colors.BOLD}python -m src.utils.tools.systemd_manager restart <tool>{Colors.NC}")
            print()

        return success

    def _update_service_file(self, service_file: Path, timeout: int) -> bool:
        """
        Update RuntimeMaxSec directive in service file.

        Args:
            service_file: Path to service file
            timeout: Timeout value in seconds (0 to disable)

        Returns:
            True if successful, False otherwise
        """
        try:
            # Read service file
            with open(service_file, 'r') as f:
                lines = f.readlines()

            # Find and update RuntimeMaxSec line
            updated = False
            new_lines = []
            skip_next = 0  # Counter to skip comment lines

            for i, line in enumerate(lines):
                # Skip lines that are part of the timeout comment block
                if skip_next > 0:
                    skip_next -= 1
                    continue

                # If we find RuntimeMaxSec, update it
                if line.strip().startswith('RuntimeMaxSec='):
                    if timeout > 0:
                        new_lines.append(f'RuntimeMaxSec={timeout}\n')
                        updated = True
                    # If timeout is 0, skip the line (remove it)
                    continue

                # If we find the comment before RuntimeMaxSec, handle the entire block
                if '# Auto-shutdown after idle timeout' in line:
                    if timeout > 0:
                        # Keep the comment block (only add once, skip duplicates)
                        new_lines.append('# Auto-shutdown after idle timeout (default 10 minutes)\n')
                        new_lines.append('# Service stops automatically, socket activation restarts it on next request\n')
                        # Skip all duplicate comment lines
                        j = i + 1
                        while j < len(lines) and '# Service stops automatically' in lines[j]:
                            j += 1
                        skip_next = j - i - 1
                    else:
                        # Skip the entire comment block if timeout is 0
                        j = i + 1
                        while j < len(lines) and ('# Service stops automatically' in lines[j] or lines[j].strip().startswith('#')):
                            j += 1
                        skip_next = j - i - 1
                    continue

                new_lines.append(line)

            # If RuntimeMaxSec wasn't found and timeout > 0, add it before [Install]
            if not updated and timeout > 0:
                insert_idx = None
                for i, line in enumerate(new_lines):
                    if line.strip() == '[Install]':
                        insert_idx = i
                        break

                if insert_idx is not None:
                    new_lines.insert(insert_idx, '\n')
                    new_lines.insert(insert_idx + 1, '# Auto-shutdown after idle timeout (default 10 minutes)\n')
                    new_lines.insert(insert_idx + 2, '# Service stops automatically, socket activation restarts it on next request\n')
                    new_lines.insert(insert_idx + 3, f'RuntimeMaxSec={timeout}\n')

            # Write updated service file
            with open(service_file, 'w') as f:
                f.writelines(new_lines)

            return True

        except Exception as e:
            print(f"{Colors.RED}Error updating {service_file}:{Colors.NC} {e}", file=sys.stderr)
            return False

    def _format_timeout(self, seconds: int) -> str:
        """
        Format timeout in human-readable format.

        Args:
            seconds: Timeout in seconds

        Returns:
            Human-readable string
        """
        if seconds == 0:
            return "Disabled"
        elif seconds < 60:
            return f"{seconds} seconds"
        elif seconds < 3600:
            minutes = seconds / 60
            return f"{minutes:.1f} minutes"
        else:
            hours = seconds / 3600
            return f"{hours:.1f} hours"


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Manage auto-shutdown timeouts for RAG tools',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show current timeouts
  python -m src.utils.tools.timeout_manager show

  # Set office tool to 15 minutes
  python -m src.utils.tools.timeout_manager set office 900

  # Set all tools to 20 minutes
  python -m src.utils.tools.timeout_manager set all 1200

  # Disable auto-shutdown for GPU tool
  python -m src.utils.tools.timeout_manager set gpu 0

  # Apply changes to systemd services
  python -m src.utils.tools.timeout_manager apply

  # Set and apply in one step
  python -m src.utils.tools.timeout_manager set office 600
  python -m src.utils.tools.timeout_manager apply
        """
    )

    parser.add_argument(
        'command',
        choices=['show', 'set', 'apply'],
        help='Command to execute'
    )

    parser.add_argument(
        'tool',
        nargs='?',
        help='Tool name for set command (office, archive, ocr, gpu, or all)'
    )

    parser.add_argument(
        'timeout',
        nargs='?',
        type=int,
        help='Timeout value in seconds (0 to disable)'
    )

    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help='Suppress output'
    )

    args = parser.parse_args()

    manager = TimeoutManager()
    verbose = not args.quiet

    try:
        if args.command == 'show':
            manager.show_timeouts(verbose=verbose)
            sys.exit(0)

        elif args.command == 'set':
            if not args.tool:
                print(f"{Colors.RED}Error:{Colors.NC} set command requires a tool name")
                print(f"Usage: python -m src.utils.tools.timeout_manager set <tool> <timeout>")
                print(f"Valid tools: {', '.join(manager.TOOLS)} or 'all'")
                sys.exit(1)

            if args.timeout is None:
                print(f"{Colors.RED}Error:{Colors.NC} set command requires a timeout value")
                print(f"Usage: python -m src.utils.tools.timeout_manager set <tool> <timeout>")
                sys.exit(1)

            success = manager.set_timeout(args.tool, args.timeout, verbose=verbose)
            sys.exit(0 if success else 1)

        elif args.command == 'apply':
            success = manager.apply_timeouts(verbose=verbose)
            sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}Interrupted{Colors.NC}")
        sys.exit(130)
    except Exception as e:
        print(f"{Colors.RED}Error:{Colors.NC} {e}")
        if verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
