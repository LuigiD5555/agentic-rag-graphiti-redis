#!/usr/bin/env python3
"""
Systemd Socket Activation Manager for RAG Tools

This module manages the lifecycle of preprocessing tool containers using systemd
socket activation. Tools (office, archive, ocr, gpu) start on-demand when needed
and stop when idle, saving resources.

Usage:
    python -m src.tools.systemd_manager install   # Install systemd units
    python -m src.tools.systemd_manager enable    # Enable sockets (on-demand)
    python -m src.tools.systemd_manager verify    # Verify configuration
    python -m src.tools.systemd_manager status    # Show status
    python -m src.tools.systemd_manager fix       # Auto-repair configuration

Design:
    - Sockets listen on ports (9101-9104) without overhead
    - Services are inactive until first request
    - On connection, systemd auto-starts the container
    - No code changes needed in the RAG application
"""

import subprocess
import sys
from pathlib import Path
from typing import List, Tuple, Dict
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


class SystemdManager:
    """
    Manages systemd socket activation for preprocessing tools.

    Attributes:
        project_root: Path to project root directory
        systemd_dir: Path to systemd unit files in project
        user_systemd_dir: Path to user's systemd directory
        tools: List of tool names to manage
    """

    TOOLS = ['office', 'archive', 'ocr', 'gpu']

    def __init__(self):
        """Initialize manager with project paths."""
        self.project_root = Path(__file__).parent.parent.parent
        self.systemd_dir = self.project_root / 'systemd' / 'user'
        self.user_systemd_dir = Path.home() / '.config' / 'systemd' / 'user'
        self.env_file = self.project_root / '.env'

    def _run_command(self, cmd: List[str], check: bool = True, capture: bool = True) -> Tuple[int, str, str]:
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

    def _read_env_var(self, var_name: str) -> bool:
        """
        Check if environment variable is set to 'true' in .env file.

        Args:
            var_name: Variable name to check

        Returns:
            True if variable is set to 'true'
        """
        if not self.env_file.exists():
            return False

        with open(self.env_file, 'r') as f:
            for line in f:
                if line.strip().startswith(f'{var_name}=true'):
                    return True
        return False

    def _should_enable_tool(self, tool: str) -> bool:
        """
        Check if a tool should be enabled based on .env configuration.

        Args:
            tool: Tool name (office, archive, ocr, gpu)

        Returns:
            True if tool should be enabled
        """
        if tool in ['office', 'archive']:
            return True  # Always enable
        elif tool == 'ocr':
            return self._read_env_var('ENABLE_OCR')
        elif tool == 'gpu':
            return self._read_env_var('ENABLE_GPU_ACCELERATION')
        return False

    def install(self, verbose: bool = True) -> bool:
        """
        Install systemd units to user's systemd directory.

        Copies .socket and .service files from project to ~/.config/systemd/user/
        and creates necessary cache directories.

        Args:
            verbose: Print status messages

        Returns:
            True if successful
        """
        if not self._check_systemd():
            print(f"{Colors.RED}✗ FAIL:{Colors.NC} systemctl not available")
            return False

        if verbose:
            print(f"{Colors.CYAN}Installing systemd units...{Colors.NC}")

        # Create user systemd directory
        self.user_systemd_dir.mkdir(parents=True, exist_ok=True)

        # Copy unit files
        for tool in self.TOOLS:
            socket_file = self.systemd_dir / f'tool-{tool}.socket'
            service_file = self.systemd_dir / f'tool-{tool}.service'

            if not socket_file.exists() or not service_file.exists():
                print(f"{Colors.YELLOW}⚠ WARN:{Colors.NC} Missing files for tool-{tool}")
                continue

            shutil.copy2(socket_file, self.user_systemd_dir)
            shutil.copy2(service_file, self.user_systemd_dir)

            if verbose:
                print(f"  {Colors.GREEN}✓{Colors.NC} Installed tool-{tool} units")

        # Create cache directories
        cache_dir = Path.home() / '.cache' / 'rag-tools'
        for tool in self.TOOLS:
            tool_cache = cache_dir / tool
            tool_cache.mkdir(parents=True, exist_ok=True)

        if verbose:
            print(f"  {Colors.GREEN}✓{Colors.NC} Created cache directories")

        # Reload systemd
        self._run_command(['systemctl', '--user', 'daemon-reload'])

        if verbose:
            print(f"{Colors.GREEN}✓ Installation complete{Colors.NC}")

        return True

    def enable(self, verbose: bool = True) -> bool:
        """
        Enable socket activation for tools.

        Enables ONLY the sockets (not services) and ensures services are disabled
        to prevent auto-start. Services will be started by systemd when the socket
        receives a connection.

        Args:
            verbose: Print status messages

        Returns:
            True if successful
        """
        if not self._check_systemd():
            print(f"{Colors.RED}✗ FAIL:{Colors.NC} systemctl not available")
            return False

        # Install if not already installed
        if not (self.user_systemd_dir / 'tool-office.socket').exists():
            if verbose:
                print("Units not installed, installing first...")
            self.install(verbose=verbose)

        if verbose:
            print(f"{Colors.CYAN}Enabling socket activation...{Colors.NC}")
            print("Note: Only sockets enabled, services start on-demand")
            print()

        # Disable all services explicitly (prevent auto-start)
        for tool in self.TOOLS:
            self._run_command(
                ['systemctl', '--user', 'disable', f'tool-{tool}.service'],
                check=False,
                capture=True
            )

        # Enable and start sockets based on configuration
        for tool in self.TOOLS:
            if not self._should_enable_tool(tool):
                if verbose:
                    print(f"  {Colors.YELLOW}⊘{Colors.NC} Skipping tool-{tool} (not enabled in .env)")
                continue

            # Enable socket
            code, _, _ = self._run_command(
                ['systemctl', '--user', 'enable', f'tool-{tool}.socket'],
                check=False
            )

            # Start socket
            code2, _, _ = self._run_command(
                ['systemctl', '--user', 'start', f'tool-{tool}.socket'],
                check=False
            )

            if code == 0 and code2 == 0:
                if verbose:
                    print(f"  {Colors.GREEN}✓{Colors.NC} Enabled tool-{tool}.socket")
            else:
                if verbose:
                    print(f"  {Colors.RED}✗{Colors.NC} Failed to enable tool-{tool}.socket")

        if verbose:
            print(f"\n{Colors.GREEN}✓ Socket activation enabled{Colors.NC}")
            print("Sockets will automatically start services when needed")

        return True

    def verify(self, verbose: bool = True) -> Tuple[bool, int, int]:
        """
        Verify socket activation configuration.

        Checks:
        - systemd availability
        - .service and .socket files exist
        - Units are installed in user systemd directory
        - Sockets are enabled and active
        - Services are NOT auto-enabled
        - Container images exist

        Args:
            verbose: Print detailed verification output

        Returns:
            Tuple of (success, error_count, warning_count)
        """
        errors = 0
        warnings = 0

        if verbose:
            print(f"{Colors.BLUE}{'='*70}{Colors.NC}")
            print(f"{Colors.BOLD}Socket Activation Configuration Verification{Colors.NC}")
            print(f"{Colors.BLUE}{'='*70}{Colors.NC}\n")

        # Check 1: systemd availability
        if verbose:
            print(f"{Colors.CYAN}[1/6] Checking systemd availability...{Colors.NC}")

        if not self._check_systemd():
            if verbose:
                print(f"  {Colors.RED}✗ FAIL:{Colors.NC} systemctl not available")
            return False, 1, 0

        if verbose:
            print(f"  {Colors.GREEN}✓ PASS:{Colors.NC} systemctl available\n")

        # Check 2: Service files exist
        if verbose:
            print(f"{Colors.CYAN}[2/6] Checking .service files exist...{Colors.NC}")

        for tool in self.TOOLS:
            service_file = self.systemd_dir / f'tool-{tool}.service'
            if service_file.exists():
                if verbose:
                    print(f"  {Colors.GREEN}✓ PASS:{Colors.NC} tool-{tool}.service exists")
            else:
                if verbose:
                    print(f"  {Colors.YELLOW}⚠ WARN:{Colors.NC} tool-{tool}.service not found")
                warnings += 1

        if verbose:
            print()

        # Check 3: Socket files exist
        if verbose:
            print(f"{Colors.CYAN}[3/6] Checking .socket files exist...{Colors.NC}")

        for tool in self.TOOLS:
            socket_file = self.systemd_dir / f'tool-{tool}.socket'
            if socket_file.exists():
                if verbose:
                    print(f"  {Colors.GREEN}✓ PASS:{Colors.NC} tool-{tool}.socket exists")
            else:
                if verbose:
                    print(f"  {Colors.RED}✗ FAIL:{Colors.NC} tool-{tool}.socket not found")
                errors += 1

        if verbose:
            print()

        # Check 4: Installed units
        if verbose:
            print(f"{Colors.CYAN}[4/6] Checking installed systemd units...{Colors.NC}")

        for tool in ['office', 'archive']:  # Always check these two
            socket_installed = (self.user_systemd_dir / f'tool-{tool}.socket').exists()
            service_installed = (self.user_systemd_dir / f'tool-{tool}.service').exists()

            if socket_installed:
                if verbose:
                    print(f"  {Colors.GREEN}✓ PASS:{Colors.NC} tool-{tool}.socket installed")
            else:
                if verbose:
                    print(f"  {Colors.YELLOW}⚠ WARN:{Colors.NC} tool-{tool}.socket not installed")
                warnings += 1

            if service_installed:
                if verbose:
                    print(f"  {Colors.GREEN}✓ PASS:{Colors.NC} tool-{tool}.service installed")
            else:
                if verbose:
                    print(f"  {Colors.YELLOW}⚠ WARN:{Colors.NC} tool-{tool}.service not installed")
                warnings += 1

        if verbose:
            print()

        # Check 5: Runtime status
        if verbose:
            print(f"{Colors.CYAN}[5/6] Checking runtime status...{Colors.NC}")

        for tool in ['office', 'archive']:
            # Check socket status
            _, socket_status, _ = self._run_command(
                ['systemctl', '--user', 'is-active', f'tool-{tool}.socket'],
                check=False
            )
            socket_status = socket_status.strip()

            _, socket_enabled, _ = self._run_command(
                ['systemctl', '--user', 'is-enabled', f'tool-{tool}.socket'],
                check=False
            )
            socket_enabled = socket_enabled.strip()

            # Check if socket is enabled
            if socket_enabled in ['enabled', 'static']:
                if verbose:
                    print(f"  {Colors.GREEN}✓ PASS:{Colors.NC} tool-{tool}.socket is enabled")
            else:
                if verbose:
                    print(f"  {Colors.YELLOW}⚠ WARN:{Colors.NC} tool-{tool}.socket is not enabled")
                warnings += 1

            # Check if socket is active
            if socket_status == 'active':
                if verbose:
                    print(f"  {Colors.GREEN}✓ PASS:{Colors.NC} tool-{tool}.socket is active (listening)")
            else:
                if verbose:
                    print(f"  {Colors.YELLOW}⚠ WARN:{Colors.NC} tool-{tool}.socket is {socket_status}")
                warnings += 1

            # Check service status
            _, service_enabled, _ = self._run_command(
                ['systemctl', '--user', 'is-enabled', f'tool-{tool}.service'],
                check=False
            )
            service_enabled = service_enabled.strip()

            _, service_status, _ = self._run_command(
                ['systemctl', '--user', 'is-active', f'tool-{tool}.service'],
                check=False
            )
            service_status = service_status.strip()

            # Check if service is NOT auto-enabled
            if service_enabled in ['disabled', 'indirect', 'static']:
                if verbose:
                    print(f"  {Colors.GREEN}✓ PASS:{Colors.NC} tool-{tool}.service is not auto-enabled (correct)")
            else:
                if verbose:
                    print(f"  {Colors.RED}✗ FAIL:{Colors.NC} tool-{tool}.service is enabled (should be disabled)")
                errors += 1

            # Check service status
            if service_status == 'inactive':
                if verbose:
                    print(f"  {Colors.GREEN}✓ PASS:{Colors.NC} tool-{tool}.service is inactive (will start on-demand)")
            elif service_status == 'active':
                if verbose:
                    print(f"  {Colors.BLUE}ℹ INFO:{Colors.NC} tool-{tool}.service is active (responding to requests)")
            else:
                if verbose:
                    print(f"  {Colors.YELLOW}⚠ WARN:{Colors.NC} tool-{tool}.service is {service_status}")
                warnings += 1

            if verbose:
                print()

        # Check 6: Container images
        if verbose:
            print(f"{Colors.CYAN}[6/6] Checking container images...{Colors.NC}")

        if shutil.which('podman'):
            code, stdout, _ = self._run_command(['podman', 'images', '--format', '{{.Repository}}'], check=False)
            if code == 0:
                images = stdout.strip().split('\n')
                for tool in ['office', 'archive']:
                    if f'localhost/rag-tool-{tool}' in images:
                        if verbose:
                            print(f"  {Colors.GREEN}✓ PASS:{Colors.NC} rag-tool-{tool} image exists")
                    else:
                        if verbose:
                            print(f"  {Colors.RED}✗ FAIL:{Colors.NC} rag-tool-{tool} image not found")
                        errors += 1
        else:
            if verbose:
                print(f"  {Colors.YELLOW}⚠ WARN:{Colors.NC} podman not available, skipping image check")
            warnings += 1

        if verbose:
            print()

        # Summary
        if verbose:
            print(f"{Colors.BLUE}{'='*70}{Colors.NC}")
            print(f"{Colors.BOLD}Summary{Colors.NC}")
            print(f"{Colors.BLUE}{'='*70}{Colors.NC}\n")

        success = errors == 0

        if verbose:
            if errors == 0 and warnings == 0:
                print(f"{Colors.GREEN}{Colors.BOLD}✓ ALL CHECKS PASSED{Colors.NC}\n")
                print("Socket activation is correctly configured!")
            elif errors == 0:
                print(f"{Colors.YELLOW}{Colors.BOLD}⚠ WARNINGS: {warnings}{Colors.NC}\n")
                print("Configuration has minor issues but should work.")
            else:
                print(f"{Colors.RED}{Colors.BOLD}✗ ERRORS: {errors}, WARNINGS: {warnings}{Colors.NC}\n")
                print("Configuration has issues that need to be fixed.")
                print(f"Run: {Colors.CYAN}python -m src.tools.systemd_manager fix{Colors.NC}")

        return success, errors, warnings

    def fix(self, verbose: bool = True) -> bool:
        """
        Auto-repair socket activation configuration.

        Stops and disables services, reinstalls units, enables only sockets.
        Safe to run multiple times.

        Args:
            verbose: Print status messages

        Returns:
            True if successful
        """
        if not self._check_systemd():
            print(f"{Colors.RED}✗ FAIL:{Colors.NC} systemctl not available")
            return False

        if verbose:
            print(f"{Colors.BLUE}{'='*70}{Colors.NC}")
            print(f"{Colors.BOLD}Fixing Socket Activation Configuration{Colors.NC}")
            print(f"{Colors.BLUE}{'='*70}{Colors.NC}\n")

        # Step 1: Stop and disable services
        if verbose:
            print(f"{Colors.CYAN}Step 1: Stopping and disabling services...{Colors.NC}\n")

        for tool in self.TOOLS:
            self._run_command(['systemctl', '--user', 'stop', f'tool-{tool}.service'], check=False, capture=True)
            self._run_command(['systemctl', '--user', 'disable', f'tool-{tool}.service'], check=False, capture=True)
            self._run_command(['systemctl', '--user', 'stop', f'tool-{tool}.socket'], check=False, capture=True)

        if verbose:
            print(f"  {Colors.GREEN}✓{Colors.NC} All services stopped and disabled\n")

        # Step 2: Stop containers
        if verbose:
            print(f"{Colors.CYAN}Step 2: Stopping containers...{Colors.NC}\n")

        if shutil.which('podman'):
            for tool in self.TOOLS:
                self._run_command(['podman', 'stop', '-t', '5', f'rag-tool-{tool}'], check=False, capture=True)
                self._run_command(['podman', 'rm', '-f', f'rag-tool-{tool}'], check=False, capture=True)

        if verbose:
            print(f"  {Colors.GREEN}✓{Colors.NC} All containers stopped\n")

        # Step 3: Reinstall units
        if verbose:
            print(f"{Colors.CYAN}Step 3: Reinstalling systemd units...{Colors.NC}\n")

        self.install(verbose=False)

        if verbose:
            print(f"  {Colors.GREEN}✓{Colors.NC} Units reinstalled\n")

        # Step 4: Enable sockets
        if verbose:
            print(f"{Colors.CYAN}Step 4: Enabling sockets...{Colors.NC}\n")

        self.enable(verbose=False)

        if verbose:
            print(f"  {Colors.GREEN}✓{Colors.NC} Sockets enabled\n")

        # Step 5: Verify
        if verbose:
            print(f"{Colors.CYAN}Step 5: Verifying configuration...{Colors.NC}\n")

        success, errors, warnings = self.verify(verbose=False)

        if verbose:
            print(f"{Colors.BLUE}{'='*70}{Colors.NC}")
            print(f"{Colors.BOLD}Fix Complete{Colors.NC}")
            print(f"{Colors.BLUE}{'='*70}{Colors.NC}\n")

            if success and warnings == 0:
                print(f"{Colors.GREEN}✓ All issues resolved{Colors.NC}\n")
            elif errors == 0:
                print(f"{Colors.YELLOW}⚠ Fixed with {warnings} warnings{Colors.NC}\n")
            else:
                print(f"{Colors.RED}✗ Some issues remain ({errors} errors, {warnings} warnings){Colors.NC}\n")

        return success

    def build(self, tools: List[str] = None, verbose: bool = True) -> bool:
        """
        Build container images for tools.

        Args:
            tools: List of tool names to build (default: all tools)
            verbose: Print build output

        Returns:
            True if all builds succeed, False otherwise
        """
        if tools is None:
            tools = self.TOOLS

        # Validate tool names
        invalid_tools = [t for t in tools if t not in self.TOOLS]
        if invalid_tools:
            if verbose:
                print(f"{Colors.RED}✗ Invalid tool names:{Colors.NC} {', '.join(invalid_tools)}")
                print(f"  Valid tools: {', '.join(self.TOOLS)}")
            return False

        tools_dir = self.project_root / 'tools'
        if not tools_dir.exists():
            if verbose:
                print(f"{Colors.RED}✗ Tools directory not found:{Colors.NC} {tools_dir}")
            return False

        if verbose:
            print(f"{Colors.BLUE}{'='*70}{Colors.NC}")
            print(f"{Colors.BOLD}Building RAG Tool Images{Colors.NC}")
            print(f"{Colors.BLUE}{'='*70}{Colors.NC}\n")

        all_success = True

        for tool in tools:
            tool_dir = tools_dir / tool
            if not tool_dir.exists():
                if verbose:
                    print(f"{Colors.YELLOW}⚠ Skipping:{Colors.NC} {tool} (directory not found)")
                continue

            if verbose:
                print(f"{Colors.CYAN}Building tool-{tool}...{Colors.NC}")

            # Build image
            code, stdout, stderr = self._run_command(
                ['podman', 'build', '-t', f'rag-tool-{tool}:latest', str(tool_dir)],
                check=False,
                capture=True
            )

            if code == 0:
                if verbose:
                    print(f"  {Colors.GREEN}✓ tool-{tool} built successfully{Colors.NC}\n")
            else:
                if verbose:
                    print(f"  {Colors.RED}✗ tool-{tool} build failed{Colors.NC}")
                    if stderr:
                        print(f"  Error: {stderr[:200]}")
                    print()
                all_success = False

        # Show final images
        if verbose and all_success:
            print(f"{Colors.BLUE}{'='*70}{Colors.NC}")
            print(f"{Colors.BOLD}Built Images:{Colors.NC}\n")

            code, stdout, _ = self._run_command(
                ['podman', 'images'],
                check=False,
                capture=True
            )

            if code == 0:
                for line in stdout.split('\n'):
                    if 'rag-tool' in line:
                        print(f"  {line}")
            print()

        return all_success

    def restart(self, tool: str, verbose: bool = True) -> bool:
        """
        Restart a specific tool (socket + service).

        Args:
            tool: Tool name to restart (office, archive, ocr, gpu)
            verbose: Print restart progress

        Returns:
            True if restart succeeds, False otherwise
        """
        if tool not in self.TOOLS:
            if verbose:
                print(f"{Colors.RED}✗ Invalid tool:{Colors.NC} {tool}")
                print(f"  Valid tools: {', '.join(self.TOOLS)}")
            return False

        if not self._check_systemd():
            if verbose:
                print(f"{Colors.RED}✗ systemctl not available{Colors.NC}")
            return False

        # Get port for this tool
        port_map = {'office': 9102, 'archive': 9101, 'ocr': 9103, 'gpu': 9104}
        port = port_map.get(tool)

        if verbose:
            print(f"{Colors.BLUE}{'='*70}{Colors.NC}")
            print(f"{Colors.BOLD}Restarting tool-{tool}{Colors.NC}")
            print(f"{Colors.BLUE}{'='*70}{Colors.NC}\n")

        # Step 1: Stop socket and service
        if verbose:
            print(f"{Colors.CYAN}Step 1: Stopping socket and service...{Colors.NC}")

        self._run_command(['systemctl', '--user', 'stop', f'tool-{tool}.socket'], check=False, capture=True)
        self._run_command(['systemctl', '--user', 'stop', f'tool-{tool}.service'], check=False, capture=True)

        if verbose:
            print(f"  {Colors.GREEN}✓ Stopped{Colors.NC}\n")

        # Step 2: Reload systemd
        if verbose:
            print(f"{Colors.CYAN}Step 2: Reloading systemd...{Colors.NC}")

        self._run_command(['systemctl', '--user', 'daemon-reload'], check=False, capture=True)

        if verbose:
            print(f"  {Colors.GREEN}✓ Reloaded{Colors.NC}\n")

        # Step 3: Start socket
        if verbose:
            print(f"{Colors.CYAN}Step 3: Starting socket...{Colors.NC}")

        code, _, stderr = self._run_command(
            ['systemctl', '--user', 'start', f'tool-{tool}.socket'],
            check=False,
            capture=True
        )

        if code != 0:
            if verbose:
                print(f"  {Colors.RED}✗ Failed to start socket{Colors.NC}")
                if stderr:
                    print(f"  Error: {stderr}")
            return False

        if verbose:
            print(f"  {Colors.GREEN}✓ Socket started{Colors.NC}\n")

        # Step 4: Health check
        if verbose:
            print(f"{Colors.CYAN}Step 4: Health check (activating socket)...{Colors.NC}")

        import time
        time.sleep(1)  # Give socket a moment to listen

        code, _, _ = self._run_command(
            ['curl', '-s', '-f', '-m', '10', f'http://127.0.0.1:{port}/healthz'],
            check=False,
            capture=True
        )

        if code == 0:
            if verbose:
                print(f"  {Colors.GREEN}✓ tool-{tool} responding on port {port}{Colors.NC}\n")
        else:
            if verbose:
                msg = f"  {Colors.YELLOW}⚠ tool-{tool} not responding yet "
                msg += f"(may start on first real request){Colors.NC}\n"
                print(msg)

        # Step 5: Verify /work permissions (optional, only if container is running)
        if shutil.which('podman'):
            if verbose:
                print(f"{Colors.CYAN}Step 5: Verifying /work permissions...{Colors.NC}")

            code, _, _ = self._run_command(
                ['podman', 'exec', f'rag-tool-{tool}', 'sh', '-c', 'touch /work/_test && rm /work/_test'],
                check=False,
                capture=True
            )

            if code == 0:
                if verbose:
                    print(f"  {Colors.GREEN}✓ /work is writable{Colors.NC}\n")
            else:
                if verbose:
                    print(f"  {Colors.YELLOW}⚠ Container not running yet or /work not writable{Colors.NC}\n")

        if verbose:
            print(f"{Colors.GREEN}✓ Restart complete{Colors.NC}\n")

        return True

    def status(self, verbose: bool = True) -> Dict[str, Dict[str, str]]:
        """
        Show current status of all tools.

        Args:
            verbose: Print status table

        Returns:
            Dictionary with status information for each tool
        """
        if not self._check_systemd():
            print(f"{Colors.RED}✗ FAIL:{Colors.NC} systemctl not available")
            return {}

        status_info = {}

        for tool in self.TOOLS:
            if not self._should_enable_tool(tool):
                continue

            # Get socket status
            _, socket_active, _ = self._run_command(
                ['systemctl', '--user', 'is-active', f'tool-{tool}.socket'],
                check=False
            )

            # Get service status
            _, service_active, _ = self._run_command(
                ['systemctl', '--user', 'is-active', f'tool-{tool}.service'],
                check=False
            )

            # Get container status
            container_status = 'stopped'
            if shutil.which('podman'):
                code, _, _ = self._run_command(
                    ['podman', 'inspect', f'rag-tool-{tool}'],
                    check=False,
                    capture=True
                )
                if code == 0:
                    container_status = 'running'

            status_info[tool] = {
                'socket': socket_active.strip(),
                'service': service_active.strip(),
                'container': container_status
            }

        if verbose:
            print(f"\n{Colors.BOLD}Tool Status:{Colors.NC}\n")
            print(f"{'Tool':<10} {'Socket':<12} {'Service':<12} {'Container':<12}")
            print("-" * 50)

            for tool, info in status_info.items():
                socket_color = Colors.GREEN if info['socket'] == 'active' else Colors.YELLOW
                service_color = Colors.GREEN if info['service'] == 'active' else Colors.NC
                container_color = Colors.GREEN if info['container'] == 'running' else Colors.NC

                print(f"{tool:<10} {socket_color}{info['socket']:<12}{Colors.NC} "
                      f"{service_color}{info['service']:<12}{Colors.NC} "
                      f"{container_color}{info['container']:<12}{Colors.NC}")

            print()

        return status_info


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Systemd Socket Activation Manager for RAG Tools',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  install   Install systemd units to user directory
  enable    Enable socket activation (sockets only, services on-demand)
  verify    Verify configuration is correct
  fix       Auto-repair any configuration issues
  status    Show current status of all tools
  build     Build container images for tools
  restart   Restart a specific tool (socket + service)

Examples:
  # Initial setup
  python -m src.tools.systemd_manager build
  python -m src.tools.systemd_manager install
  python -m src.tools.systemd_manager enable

  # Check if everything is working
  python -m src.tools.systemd_manager verify

  # Fix problems automatically
  python -m src.tools.systemd_manager fix

  # See what's running
  python -m src.tools.systemd_manager status

  # Restart a specific tool
  python -m src.tools.systemd_manager restart office

How it works:
  - Sockets listen on ports (9101-9104) without overhead
  - Services are inactive until first request
  - On connection, systemd auto-starts the container
  - Tools start in 1-2 seconds when needed
  - No code changes needed in RAG application
        """
    )

    parser.add_argument(
        'command',
        choices=['install', 'enable', 'verify', 'fix', 'status', 'build', 'restart'],
        help='Command to execute'
    )

    parser.add_argument(
        'tool',
        nargs='?',
        help='Tool name for restart command (office, archive, ocr, gpu)'
    )

    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help='Suppress output (exit code indicates success/failure)'
    )

    parser.add_argument(
        '--tools',
        nargs='+',
        help='Specific tools to build (default: all)'
    )

    args = parser.parse_args()

    manager = SystemdManager()
    verbose = not args.quiet

    try:
        if args.command == 'install':
            success = manager.install(verbose=verbose)
        elif args.command == 'enable':
            success = manager.enable(verbose=verbose)
        elif args.command == 'verify':
            success, errors, warnings = manager.verify(verbose=verbose)
        elif args.command == 'fix':
            success = manager.fix(verbose=verbose)
        elif args.command == 'status':
            manager.status(verbose=verbose)
            success = True
        elif args.command == 'build':
            tools = args.tools if args.tools else None
            success = manager.build(tools=tools, verbose=verbose)
        elif args.command == 'restart':
            if not args.tool:
                print(f"{Colors.RED}Error:{Colors.NC} restart command requires a tool name")
                print(f"Usage: python -m src.tools.systemd_manager restart <tool>")
                print(f"Valid tools: {', '.join(manager.TOOLS)}")
                sys.exit(1)
            success = manager.restart(args.tool, verbose=verbose)

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
