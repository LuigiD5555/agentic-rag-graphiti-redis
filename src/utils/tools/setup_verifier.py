#!/usr/bin/env python3
"""
RAG Tools - Setup Verification Module

Comprehensive verification of RAG tools installation and configuration.
Can be used via CLI or imported programmatically (e.g., by a GUI).

Usage:
    # CLI mode (human-readable output)
    python -m src.utils.tools.setup_verifier

    # Quiet mode (exit code only)
    python -m src.utils.tools.setup_verifier --quiet

    # JSON output (machine-readable, for GUI integration)
    python -m src.utils.tools.setup_verifier --json

    # Programmatic usage
    from src.utils.tools.setup_verifier import SetupVerifier
    verifier = SetupVerifier()
    results = verifier.verify_all()
    if results['success']:
        print("All checks passed!")
"""

import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List


class Colors:
    """ANSI color codes for terminal output."""
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    BOLD = '\033[1m'
    NC = '\033[0m'  # No Color


@dataclass
class CheckResult:
    """Result of a single verification check."""
    passed: bool
    level: str  # 'ok', 'warning', 'error'
    description: str
    details: str = ""
    file_path: str = ""


@dataclass
class CategoryResult:
    """Result of a category of checks."""
    name: str
    checks: List[CheckResult] = field(default_factory=list)
    errors: int = 0
    warnings: int = 0
    passed: int = 0

    def add_check(self, result: CheckResult):
        """Add a check result and update counters."""
        self.checks.append(result)
        if result.level == 'error':
            self.errors += 1
        elif result.level == 'warning':
            self.warnings += 1
        elif result.level == 'ok':
            self.passed += 1


class SetupVerifier:
    """Verify RAG tools setup and configuration."""

    TOOLS = ['office', 'archive', 'ocr', 'gpu']
    PORT_MAP = {
        'archive': (9101, 19101),
        'office': (9102, 19102),
        'ocr': (9103, 19103),
        'gpu': (9104, 19104)
    }

    def __init__(self):
        """Initialize verifier with project paths."""
        self.script_dir = Path(__file__).parent.parent.parent.parent
        self.project_root = self.script_dir
        self.tools_dir = self.project_root / 'tools'
        self.systemd_dir = self.project_root / 'systemd' / 'user'

    def _check_file(
        self,
        file_path: Path,
        description: str
    ) -> CheckResult:
        """Check if a file exists."""
        if file_path.exists() and file_path.is_file():
            return CheckResult(
                passed=True,
                level='ok',
                description=description,
                file_path=str(file_path)
            )
        else:
            return CheckResult(
                passed=False,
                level='error',
                description=description,
                details=f"NOT FOUND: {file_path}",
                file_path=str(file_path)
            )

    def _check_dir(
        self,
        dir_path: Path,
        description: str
    ) -> CheckResult:
        """Check if a directory exists."""
        if dir_path.exists() and dir_path.is_dir():
            return CheckResult(
                passed=True,
                level='ok',
                description=description,
                file_path=str(dir_path)
            )
        else:
            return CheckResult(
                passed=False,
                level='error',
                description=description,
                details=f"NOT FOUND: {dir_path}",
                file_path=str(dir_path)
            )

    def _check_executable(
        self,
        file_path: Path,
        description: str
    ) -> CheckResult:
        """Check if a file exists and is executable."""
        if not file_path.exists():
            return CheckResult(
                passed=False,
                level='error',
                description=description,
                details=f"NOT FOUND: {file_path}",
                file_path=str(file_path)
            )

        import os
        if os.access(file_path, os.X_OK):
            return CheckResult(
                passed=True,
                level='ok',
                description=f"{description} (executable)",
                file_path=str(file_path)
            )
        else:
            return CheckResult(
                passed=False,
                level='warning',
                description=f"{description} (not executable)",
                file_path=str(file_path)
            )

    def _check_command(
        self,
        command: str,
        description: str
    ) -> CheckResult:
        """Check if a command is available."""
        if shutil.which(command):
            # Try to get version info
            try:
                result = subprocess.run(
                    [command, '--version'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                version = result.stdout.split('\n')[0]
                return CheckResult(
                    passed=True,
                    level='ok',
                    description=f"{description} ({version})",
                )
            except Exception:
                return CheckResult(
                    passed=True,
                    level='ok',
                    description=description,
                )
        else:
            return CheckResult(
                passed=False,
                level='error',
                description=description,
                details=f"{command} NOT installed"
            )

    def verify_tool_directories(self) -> CategoryResult:
        """Verify tool directories exist."""
        category = CategoryResult(name="Tool Directories")

        for tool in self.TOOLS:
            tool_dir = self.tools_dir / tool
            result = self._check_dir(
                tool_dir,
                f"{tool.capitalize()} tool directory"
            )
            category.add_check(result)

        return category

    def verify_tool_source_files(self) -> CategoryResult:
        """Verify tool source files exist."""
        category = CategoryResult(name="Tool Source Files")

        for tool in self.TOOLS:
            # Check app.py
            app_py = self.tools_dir / tool / 'src' / 'app.py'
            category.add_check(
                self._check_file(app_py, f"{tool.capitalize()} app.py")
            )

            # Check Dockerfile
            dockerfile = self.tools_dir / tool / 'Dockerfile'
            category.add_check(
                self._check_file(dockerfile, f"{tool.capitalize()} Dockerfile")
            )

            # Check requirements.txt
            requirements = self.tools_dir / tool / 'requirements.txt'
            category.add_check(
                self._check_file(
                    requirements,
                    f"{tool.capitalize()} requirements.txt"
                )
            )

        return category

    def verify_systemd_units(self) -> CategoryResult:
        """Verify systemd unit files exist."""
        category = CategoryResult(name="Systemd Units")

        for tool in self.TOOLS:
            # Check socket unit
            socket_file = self.systemd_dir / f'tool-{tool}.socket'
            category.add_check(
                self._check_file(socket_file, f"{tool.capitalize()} socket")
            )

            # Check service unit
            service_file = self.systemd_dir / f'tool-{tool}.service'
            category.add_check(
                self._check_file(service_file, f"{tool.capitalize()} service")
            )

        return category

    def verify_scripts(self) -> CategoryResult:
        """Verify management scripts exist."""
        category = CategoryResult(name="Management Scripts")

        # Main entry point
        start_everything = self.project_root / 'start-everything.sh'
        category.add_check(
            self._check_executable(start_everything, "Main entry script")
        )

        # Python systemd manager
        systemd_manager = (
            self.project_root / 'src' / 'tools' / 'systemd_manager.py'
        )
        category.add_check(
            self._check_file(systemd_manager, "Python systemd manager")
        )

        # Setup verifier (this file)
        setup_verifier = (
            self.project_root / 'src' / 'tools' / 'setup_verifier.py'
        )
        category.add_check(
            self._check_file(setup_verifier, "Python setup verifier")
        )

        return category

    def verify_documentation(self) -> CategoryResult:
        """Verify documentation files exist."""
        category = CategoryResult(name="Documentation")

        # Required docs
        required_docs = [
            (self.tools_dir / 'README.md', "Tools README"),
            (self.project_root / 'tests' / 'tools' / 'client_example.py', "Client example"),
            (self.tools_dir / 'example.env', "Environment template"),
        ]

        for file_path, description in required_docs:
            category.add_check(self._check_file(file_path, description))

        # Optional docs (warning level instead of error)
        optional_docs = [
            (self.tools_dir / 'ARCHITECTURE.md', "Architecture doc"),
            (self.tools_dir / 'CONFIGURATION.md', "Configuration doc"),
            (self.tools_dir / 'INDEX.md', "Index doc"),
            (self.project_root / 'NEXT_STEPS.md', "Next steps guide"),
            (self.project_root / 'TOOLS_DEPLOYMENT.md', "Deployment guide"),
        ]

        for file_path, description in optional_docs:
            result = self._check_file(file_path, description)
            # Downgrade missing optional docs to warnings
            if not result.passed:
                result.level = 'warning'
                result.details = f"Optional: {result.details}"
            category.add_check(result)

        return category

    def verify_port_configuration(self) -> CategoryResult:
        """Verify port configurations in systemd units."""
        category = CategoryResult(name="Port Configuration")

        # Check socket ports
        socket_ports = []
        for tool in self.TOOLS:
            socket_file = self.systemd_dir / f'tool-{tool}.socket'
            if socket_file.exists():
                content = socket_file.read_text()
                # Match patterns like "127.0.0.1:9102" or just "9102"
                match = re.search(r'ListenStream=(?:\d+\.\d+\.\d+\.\d+:)?(\d+)', content)
                if match:
                    port = int(match.group(1))
                    socket_ports.append((tool, port))

        # Verify socket ports are correct
        expected_socket_ports = sorted([p[0] for p in self.PORT_MAP.values()])
        actual_socket_ports = sorted([p[1] for p in socket_ports])

        if actual_socket_ports == expected_socket_ports:
            category.add_check(CheckResult(
                passed=True,
                level='ok',
                description="Socket ports (9101-9104)",
                details=f"Found: {', '.join(map(str, actual_socket_ports))}"
            ))
        else:
            category.add_check(CheckResult(
                passed=False,
                level='error',
                description="Socket ports mismatch",
                details=(
                    f"Expected: {', '.join(map(str, expected_socket_ports))}, "
                    f"Found: {', '.join(map(str, actual_socket_ports))}"
                )
            ))

        # Check internal ports
        internal_ports = []
        for tool in self.TOOLS:
            service_file = self.systemd_dir / f'tool-{tool}.service'
            if service_file.exists():
                content = service_file.read_text()
                match = re.search(r'191(\d{2})', content)
                if match:
                    port = int(f"191{match.group(1)}")
                    internal_ports.append((tool, port))

        # Verify internal ports are correct
        expected_internal = sorted([p[1] for p in self.PORT_MAP.values()])
        actual_internal = sorted([p[1] for p in internal_ports])

        if actual_internal == expected_internal:
            category.add_check(CheckResult(
                passed=True,
                level='ok',
                description="Internal ports (19101-19104)",
                details=f"Found: {', '.join(map(str, actual_internal))}"
            ))
        else:
            category.add_check(CheckResult(
                passed=False,
                level='error',
                description="Internal ports mismatch",
                details=(
                    f"Expected: {', '.join(map(str, expected_internal))}, "
                    f"Found: {', '.join(map(str, actual_internal))}"
                )
            ))

        return category

    def verify_prerequisites(self) -> CategoryResult:
        """Verify required system commands are available."""
        category = CategoryResult(name="Prerequisites")

        # Required commands
        category.add_check(
            self._check_command('podman', "podman installed")
        )
        category.add_check(
            self._check_command('systemctl', "systemctl available")
        )

        # Optional but recommended commands
        result = self._check_command('curl', "curl installed")
        if not result.passed:
            result.level = 'warning'
            result.details = "curl recommended for testing"
        category.add_check(result)

        # Check for systemd-socket-proxyd
        if shutil.which('systemd-socket-proxyd'):
            category.add_check(CheckResult(
                passed=True,
                level='ok',
                description="systemd-socket-proxyd available"
            ))
        else:
            # May be in /usr/lib/systemd/
            alt_path = Path('/usr/lib/systemd/systemd-socket-proxyd')
            if alt_path.exists():
                category.add_check(CheckResult(
                    passed=True,
                    level='ok',
                    description="systemd-socket-proxyd available",
                    details=f"Found at {alt_path}"
                ))
            else:
                category.add_check(CheckResult(
                    passed=False,
                    level='warning',
                    description="systemd-socket-proxyd not found",
                    details="May be at /usr/lib/systemd/"
                ))

        return category

    def verify_all(self) -> Dict:
        """
        Run all verification checks.

        Returns:
            Dictionary with verification results:
            {
                'success': bool,
                'errors': int,
                'warnings': int,
                'categories': [CategoryResult, ...]
            }
        """
        categories = [
            self.verify_tool_directories(),
            self.verify_tool_source_files(),
            self.verify_systemd_units(),
            self.verify_scripts(),
            self.verify_documentation(),
            self.verify_port_configuration(),
            self.verify_prerequisites(),
        ]

        total_errors = sum(c.errors for c in categories)
        total_warnings = sum(c.warnings for c in categories)
        total_passed = sum(c.passed for c in categories)

        return {
            'success': total_errors == 0,
            'errors': total_errors,
            'warnings': total_warnings,
            'passed': total_passed,
            'categories': categories
        }

    def print_results(self, results: Dict):
        """Print results in human-readable format."""
        print(f"{Colors.BLUE}{'='*70}{Colors.NC}")
        print(f"{Colors.BLUE}RAG Tools - Setup Verification{Colors.NC}")
        print(f"{Colors.BLUE}{'='*70}{Colors.NC}")
        print()

        for category in results['categories']:
            print(f"{category.name}...")
            print("=" * 70)

            for check in category.checks:
                if check.level == 'ok':
                    icon = f"{Colors.GREEN}✓{Colors.NC}"
                elif check.level == 'warning':
                    icon = f"{Colors.YELLOW}⚠{Colors.NC}"
                else:
                    icon = f"{Colors.RED}✗{Colors.NC}"

                print(f"{icon} {check.description}")
                if check.details:
                    print(f"  {check.details}")

            print()

        # Summary
        print("=" * 70)
        print()

        errors = results['errors']
        warnings = results['warnings']

        if errors == 0 and warnings == 0:
            print(f"{Colors.GREEN}✓ All checks passed!{Colors.NC}")
            print()
            print("Next steps:")
            print("  1. python -m src.utils.tools.systemd_manager build")
            print("  2. python -m src.utils.tools.systemd_manager install")
            print("  3. python -m src.utils.tools.systemd_manager enable")
            print("  4. python -m src.utils.tools.systemd_manager verify")
            print()
        elif errors == 0:
            print(
                f"{Colors.YELLOW}⚠ Setup complete with "
                f"{warnings} warning(s){Colors.NC}"
            )
            print()
            print("You can proceed, but check the warnings above.")
            print()
        else:
            print(
                f"{Colors.RED}✗ Setup incomplete: "
                f"{errors} error(s), {warnings} warning(s){Colors.NC}"
            )
            print()
            print("Please fix the errors above before proceeding.")
            print()

    def print_json(self, results: Dict):
        """Print results in JSON format for machine parsing."""
        output = {
            'success': results['success'],
            'errors': results['errors'],
            'warnings': results['warnings'],
            'passed': results['passed'],
            'categories': []
        }

        for category in results['categories']:
            cat_output = {
                'name': category.name,
                'errors': category.errors,
                'warnings': category.warnings,
                'passed': category.passed,
                'checks': []
            }

            for check in category.checks:
                cat_output['checks'].append({
                    'passed': check.passed,
                    'level': check.level,
                    'description': check.description,
                    'details': check.details,
                    'file_path': check.file_path
                })

            output['categories'].append(cat_output)

        print(json.dumps(output, indent=2))


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Verify RAG tools setup and configuration',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run verification with human-readable output
  python -m src.utils.tools.setup_verifier

  # Run verification in quiet mode (exit code only)
  python -m src.utils.tools.setup_verifier --quiet

  # Get JSON output for machine parsing or GUI
  python -m src.utils.tools.setup_verifier --json

Exit codes:
  0 - All checks passed
  1 - Errors found (setup incomplete)
  2 - Warnings only (setup complete but with warnings)
        """
    )

    parser.add_argument(
        '-q', '--quiet',
        action='store_true',
        help='Suppress output (exit code indicates success/failure)'
    )

    parser.add_argument(
        '--json',
        action='store_true',
        help='Output results in JSON format (for machine parsing/GUI)'
    )

    args = parser.parse_args()

    verifier = SetupVerifier()
    results = verifier.verify_all()

    if args.json:
        verifier.print_json(results)
    elif not args.quiet:
        verifier.print_results(results)

    # Exit codes
    if results['success']:
        sys.exit(0)
    elif results['errors'] == 0:
        sys.exit(2)  # Warnings only
    else:
        sys.exit(1)  # Errors found


if __name__ == '__main__':
    main()
