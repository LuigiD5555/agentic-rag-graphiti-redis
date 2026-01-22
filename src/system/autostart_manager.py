#!/usr/bin/env python3
"""
Autostart Manager for RAG Agentic Graphiti

This module manages the auto-start configuration of RAG services on system boot.
Controls whether containers start automatically when the system reboots.

Usage:
    python -m src.system.autostart_manager status   # Show current status
    python -m src.system.autostart_manager enable   # Enable auto-start
    python -m src.system.autostart_manager disable  # Disable auto-start
    python -m src.system.autostart_manager get      # Get current value (JSON)
    python -m src.system.autostart_manager set true # Set value (true/false)

API Integration:
    GET /api/system/autostart  - Returns {"enabled": true/false}
    POST /api/system/autostart - Body: {"enabled": true/false}
"""

import subprocess
import sys
import json
from pathlib import Path
from typing import Dict, Any
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


class AutostartManager:
    """
    Manages auto-start configuration for RAG services.

    Attributes:
        project_root: Path to project root directory
        env_file: Path to .env configuration file
        systemd_services: List of systemd services to manage
    """

    # Systemd services to manage for auto-start
    SYSTEMD_SERVICES = ['rag-agentic-graphiti.service', 'rag-tool-ui.socket']

    def __init__(self):
        """Initialize manager with project paths."""
        self.project_root = Path(__file__).parent.parent.parent.parent
        self.env_file = self.project_root / '.env'
        self.user_systemd_dir = Path.home() / '.config' / 'systemd' / 'user'

    def _run_command(self, cmd: list, check: bool = False, capture: bool = True) -> tuple:
        """
        Run a shell command and return exit code, stdout, stderr.

        Args:
            cmd: Command and arguments as list
            check: Raise exception on non-zero exit
            capture: Capture stdout/stderr

        Returns:
            Tuple of (exit_code, stdout, stderr)
        """
        try:
            result = subprocess.run(
                cmd,
                check=check,
                capture_output=capture,
                text=True
            )
            return result.returncode, result.stdout, result.stderr
        except subprocess.CalledProcessError as e:
            if check:
                raise
            return e.returncode, e.stdout or '', e.stderr or ''

    def _check_systemd(self) -> bool:
        """
        Check if systemd is available.

        Returns:
            True if systemd is available, False otherwise
        """
        return shutil.which('systemctl') is not None

    def get_status(self) -> Dict[str, Any]:
        """
        Get current auto-start status.

        Returns:
            Dictionary with status information
        """
        # Read from .env file
        config_value = "true"  # Default
        if self.env_file.exists():
            with open(self.env_file, 'r') as f:
                for line in f:
                    if line.strip().startswith('RAG_AUTOSTART='):
                        value = line.strip().split('=', 1)[1].strip().strip('"')
                        config_value = value
                        break

        # Check systemd service status
        systemd_status: Dict[str, Dict[str, str]] = {}
        if self._check_systemd():
            for service in self.SYSTEMD_SERVICES:
                # Check if enabled
                code, stdout, _ = self._run_command(
                    ['systemctl', '--user', 'is-enabled', service],
                    check=False,
                    capture=True
                )
                enabled = stdout.strip() if code == 0 else 'unknown'
                
                # Check if active
                code, stdout, _ = self._run_command(
                    ['systemctl', '--user', 'is-active', service],
                    check=False,
                    capture=True
                )
                active = stdout.strip() if code == 0 else 'unknown'
                
                systemd_status[service] = {
                    'enabled': enabled,
                    'active': active
                }

        return {
            'config_value': config_value,
            'enabled': config_value.lower() == 'true',
            'systemd_status': systemd_status,
            'config_source': str(self.env_file)
        }

    def set_status(self, enabled: bool, verbose: bool = True) -> Dict[str, Any]:
        """
        Set auto-start status.

        Args:
            enabled: True to enable auto-start, False to disable
            verbose: Print status messages

        Returns:
            Dictionary with operation results
        """
        results = {
            'success': True,
            'actions': [],
            'errors': []
        }

        # 1. Update .env file
        if verbose:
            print(f"{Colors.CYAN}Updating configuration in .env...{Colors.NC}")

        try:
            # Read current content
            if self.env_file.exists():
                with open(self.env_file, 'r') as f:
                    lines = f.readlines()
            else:
                lines = []

            # Update or add RAG_AUTOSTART line
            updated = False
            new_value = 'true' if enabled else 'false'
            
            for i, line in enumerate(lines):
                if line.strip().startswith('RAG_AUTOSTART='):
                    lines[i] = f'RAG_AUTOSTART={new_value}\n'
                    updated = True
                    break
            
            if not updated:
                lines.append(f'RAG_AUTOSTART={new_value}\n')

            # Write back
            with open(self.env_file, 'w') as f:
                f.writelines(lines)

            if verbose:
                print(f"  {Colors.GREEN}✓{Colors.NC} Updated .env: RAG_AUTOSTART={new_value}")
            
            results['actions'].append('env_updated')
            results['config_value'] = new_value

        except Exception as e:
            error_msg = f"Failed to update .env: {e}"
            if verbose:
                print(f"  {Colors.RED}✗{Colors.NC} {error_msg}")
            results['success'] = False
            results['errors'].append(error_msg)
            return results

        # 2. Update systemd services
        if not self._check_systemd():
            if verbose:
                print(f"{Colors.YELLOW}⚠{Colors.NC} systemctl not available, skipping systemd configuration")
            return results

        if verbose:
            print(f"{Colors.CYAN}Configuring systemd services...{Colors.NC}")

        for service in self.SYSTEMD_SERVICES:
            service_path = self.user_systemd_dir / service
            if not service_path.exists():
                if verbose:
                    print(f"  {Colors.YELLOW}⚠{Colors.NC} {service} not found, skipping")
                continue

            try:
                if enabled:
                    # Enable the service
                    code, stdout, stderr = self._run_command(
                        ['systemctl', '--user', 'enable', service],
                        check=False,
                        capture=True
                    )
                    
                    if code == 0:
                        if verbose:
                            print(f"  {Colors.GREEN}✓{Colors.NC} Enabled {service}")
                        results['actions'].append(f'enabled_{service}')
                    else:
                        error_msg = f"Failed to enable {service}: {stderr.strip()}"
                        if verbose:
                            print(f"  {Colors.RED}✗{Colors.NC} {error_msg}")
                        results['errors'].append(error_msg)
                else:
                    # Disable the service
                    code, stdout, stderr = self._run_command(
                        ['systemctl', '--user', 'disable', service],
                        check=False,
                        capture=True
                    )
                    
                    if code == 0:
                        if verbose:
                            print(f"  {Colors.GREEN}✓{Colors.NC} Disabled {service}")
                        results['actions'].append(f'disabled_{service}')
                    else:
                        error_msg = f"Failed to disable {service}: {stderr.strip()}"
                        if verbose:
                            print(f"  {Colors.RED}✗{Colors.NC} {error_msg}")
                        results['errors'].append(error_msg)

                    # Also stop if running
                    code, _, _ = self._run_command(
                        ['systemctl', '--user', 'is-active', service],
                        check=False,
                        capture=True
                    )
                    
                    if code == 0:  # Service is active
                        self._run_command(
                            ['systemctl', '--user', 'stop', service],
                            check=False,
                            capture=True
                        )
                        if verbose:
                            print(f"  {Colors.GREEN}✓{Colors.NC} Stopped {service}")
                        results['actions'].append(f'stopped_{service}')

            except Exception as e:
                error_msg = f"Error configuring {service}: {e}"
                if verbose:
                    print(f"  {Colors.RED}✗{Colors.NC} {error_msg}")
                results['errors'].append(error_msg)

        # 3. Reload systemd
        if verbose:
            print(f"{Colors.CYAN}Reloading systemd...{Colors.NC}")

        code, _, stderr = self._run_command(
            ['systemctl', '--user', 'daemon-reload'],
            check=False,
            capture=True
        )

        if code == 0:
            if verbose:
                print(f"  {Colors.GREEN}✓{Colors.NC} Systemd reloaded")
            results['actions'].append('systemd_reloaded')
        else:
            error_msg = f"Failed to reload systemd: {stderr.strip()}"
            if verbose:
                print(f"  {Colors.RED}✗{Colors.NC} {error_msg}")
            results['errors'].append(error_msg)

        # Update success status based on errors
        if results['errors']:
            results['success'] = False

        if verbose:
            if results['success']:
                status_msg = "enabled" if enabled else "disabled"
                print(f"\n{Colors.GREEN}✓ Auto-start {status_msg} successfully{Colors.NC}")
            else:
                print(f"\n{Colors.YELLOW}⚠ Auto-start configuration completed with errors{Colors.NC}")

        return results

    def print_status(self, verbose: bool = True) -> None:
        """
        Print current auto-start status in human-readable format.

        Args:
            verbose: Print detailed information
        """
        status = self.get_status()
        
        if verbose:
            print(f"{Colors.BLUE}{'='*70}{Colors.NC}")
            print(f"{Colors.BOLD}RAG Auto-Start Configuration{Colors.NC}")
            print(f"{Colors.BLUE}{'='*70}{Colors.NC}\n")
        
        # Configuration status
        config_value = status['config_value']
        enabled = status['enabled']
        
        status_color = Colors.GREEN if enabled else Colors.RED
        status_text = "ENABLED" if enabled else "DISABLED"
        
        print(f"Configuration: {status_color}{status_text}{Colors.NC}")
        print(f"Value in .env: RAG_AUTOSTART={config_value}")
        print(f"Config file: {status['config_source']}")
        print()
        
        # Systemd services status
        if verbose and status['systemd_status']:
            print(f"{Colors.CYAN}Systemd Services:{Colors.NC}")
            print(f"{'Service':<30} {'Enabled':<10} {'Active':<10}")
            print("-" * 50)
            
            for service, service_status in status['systemd_status'].items():
                enabled_status = service_status['enabled']
                active_status = service_status['active']
                
                enabled_color = Colors.GREEN if enabled_status == 'enabled' else Colors.RED
                active_color = Colors.GREEN if active_status == 'active' else Colors.YELLOW
                
                print(f"{service:<30} {enabled_color}{enabled_status:<10}{Colors.NC} "
                      f"{active_color}{active_status:<10}{Colors.NC}")
            
            print()
        
        # Summary
        if enabled:
            print(f"{Colors.GREEN}✓ Services will start automatically on system boot{Colors.NC}")
        else:
            print(f"{Colors.YELLOW}⚠ Services will NOT start automatically on system boot{Colors.NC}")
            print(f"  To start manually: {Colors.CYAN}./start-everything.sh{Colors.NC}")
        
        if verbose:
            print(f"\n{Colors.CYAN}Management commands:{Colors.NC}")
            print(f"  python -m src.system.autostart_manager enable")
            print(f"  python -m src.system.autostart_manager disable")
            print(f"  python -m src.system.autostart_manager status")

    def api_get(self) -> Dict[str, Any]:
        """
        Get status for API response.

        Returns:
            Dictionary suitable for JSON API response
        """
        status = self.get_status()
        return {
            'enabled': status['enabled'],
            'config_value': status['config_value'],
            'config_source': status['config_source'],
            'timestamp': self._get_timestamp()
        }

    def api_set(self, enabled: bool) -> Dict[str, Any]:
        """
        Set status from API request.

        Args:
            enabled: True to enable auto-start, False to disable

        Returns:
            Dictionary with operation results for API response
        """
        result = self.set_status(enabled, verbose=False)
        
        # Get updated status
        status = self.get_status()
        
        return {
            'success': result['success'],
            'enabled': status['enabled'],
            'config_value': status['config_value'],
            'actions': result.get('actions', []),
            'errors': result.get('errors', []),
            'timestamp': self._get_timestamp()
        }

    def _get_timestamp(self) -> str:
        """Get current timestamp in ISO format."""
        from datetime import datetime
        return datetime.now().isoformat()


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Auto-start Manager for RAG Agentic Graphiti',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show current status
  python -m src.system.autostart_manager status
  
  # Enable auto-start
  python -m src.system.autostart_manager enable
  
  # Disable auto-start  
  python -m src.system.autostart_manager disable
  
  # Get status as JSON (for scripts/API)
  python -m src.system.autostart_manager get
  
  # Set specific value (for scripts/API)
  python -m src.system.autostart_manager set true
  python -m src.system.autostart_manager set false

API Integration:
  GET /api/system/autostart  - Returns {"enabled": true/false, "config_value": "true/false"}
  POST /api/system/autostart - Body: {"enabled": true/false}
  
  Example Python code:
      from src.system.autostart_manager import AutostartManager
      manager = AutostartManager()
      
      # Get status
      status = manager.api_get()
      
      # Set status
      result = manager.api_set(True)
        """
    )

    parser.add_argument(
        'command',
        choices=['status', 'enable', 'disable', 'get', 'set'],
        help='Command to execute'
    )

    parser.add_argument(
        'value',
        nargs='?',
        help='Value for set command (true/false)'
    )

    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help='Suppress output (for get/set commands)'
    )

    args = parser.parse_args()
    manager = AutostartManager()
    verbose = not args.quiet

    try:
        if args.command == 'status':
            manager.print_status(verbose=verbose)
            sys.exit(0)
            
        elif args.command == 'enable':
            result = manager.set_status(True, verbose=verbose)
            sys.exit(0 if result['success'] else 1)
            
        elif args.command == 'disable':
            result = manager.set_status(False, verbose=verbose)
            sys.exit(0 if result['success'] else 1)
            
        elif args.command == 'get':
            status = manager.api_get()
            print(json.dumps(status, indent=2))
            sys.exit(0)
            
        elif args.command == 'set':
            if not args.value:
                print(f"{Colors.RED}Error:{Colors.NC} set command requires a value (true/false)")
                sys.exit(1)
                
            if args.value.lower() not in ['true', 'false']:
                print(f"{Colors.RED}Error:{Colors.NC} value must be 'true' or 'false'")
                sys.exit(1)
                
            enabled = args.value.lower() == 'true'
            result = manager.api_set(enabled)
            
            if verbose:
                if result['success']:
                    print(f"{Colors.GREEN}✓ Auto-start set to {args.value}{Colors.NC}")
                else:
                    print(f"{Colors.RED}✗ Failed to set auto-start{Colors.NC}")
                    for error in result.get('errors', []):
                        print(f"  {error}")
            
            # Also output JSON for scripting
            print(json.dumps(result, indent=2))
            sys.exit(0 if result['success'] else 1)
            
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
