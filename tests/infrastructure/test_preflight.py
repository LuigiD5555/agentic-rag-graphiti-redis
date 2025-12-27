"""
Pre-flight checks for system startup.

This module contains tests that should be run before starting the system
to ensure all dependencies, configuration, and prerequisites are met.

Usage:
    # Run all pre-flight checks
    pytest tests/infrastructure/test_preflight.py -v

    # Run only pre-flight checks (using marker)
    pytest -m preflight -v

    # Run in quiet mode (for scripts)
    pytest tests/infrastructure/test_preflight.py -q
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Tuple

import pytest

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# ============================================================================
# Pytest Markers
# ============================================================================

pytestmark = [
    pytest.mark.infrastructure,
    pytest.mark.preflight,
]


# ============================================================================
# Configuration
# ============================================================================

PROJECT_ROOT = Path(__file__).parents[2]
COMPOSE_FILE = PROJECT_ROOT / "podman-compose.yml"
ENV_FILE = PROJECT_ROOT / ".env"


# ============================================================================
# Helper Functions
# ============================================================================

def command_exists(command: str) -> bool:
    """Check if a command exists in PATH."""
    return shutil.which(command) is not None


def get_command_version(command: str, version_flag: str = "--version") -> str:
    """Get version string of a command."""
    try:
        result = subprocess.run(
            [command, version_flag],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip() + result.stderr.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return "unknown"


def check_port_available(port: int) -> bool:
    """Check if a port is available (not in use)."""
    try:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', port))
            return True
    except OSError:
        return False


def get_podman_info() -> dict:
    """Get podman system info."""
    try:
        result = subprocess.run(
            ['podman', 'info', '--format', 'json'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            import json
            return json.loads(result.stdout)
        return {}
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        return {}


# ============================================================================
# Test: System Commands
# ============================================================================

class TestSystemCommands:
    """Verify required system commands are installed."""

    @pytest.mark.parametrize("command", [
        "podman",
        "systemctl",
        "curl",
        "python3",
    ])
    def test_command_exists(self, command: str):
        """Test that required command is available in PATH."""
        assert command_exists(command), (
            f"Required command '{command}' not found in PATH. "
            f"Please install it before starting the system."
        )

        # Print version info for visibility
        version = get_command_version(command)
        print(f"\n✓ {command}: {version}")

    def test_podman_compose_available(self):
        """Test that podman-compose is available."""
        # Try both podman-compose and podman compose
        has_podman_compose = command_exists("podman-compose")

        if not has_podman_compose:
            # Check if podman compose works
            try:
                result = subprocess.run(
                    ["podman", "compose", "version"],
                    capture_output=True,
                    timeout=5,
                )
                has_podman_compose = result.returncode == 0
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

        assert has_podman_compose, (
            "podman-compose or 'podman compose' not available. "
            "Install podman-compose: pip install podman-compose"
        )

        print(f"\n✓ podman-compose: available")

    def test_pytest_available(self):
        """Test that pytest is available (for running tests)."""
        assert command_exists("pytest"), (
            "pytest not found. Install it: pip install pytest"
        )

        version = get_command_version("pytest")
        print(f"\n✓ pytest: {version}")


# ============================================================================
# Test: Configuration Files
# ============================================================================

class TestConfigurationFiles:
    """Verify required configuration files exist and are valid."""

    def test_compose_file_exists(self):
        """Test that podman-compose.yml exists."""
        assert COMPOSE_FILE.exists(), (
            f"podman-compose.yml not found at {COMPOSE_FILE}"
        )
        print(f"\n✓ Found podman-compose.yml")

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_compose_file_valid_yaml(self):
        """Test that podman-compose.yml is valid YAML."""
        try:
            content = yaml.safe_load(COMPOSE_FILE.read_text())
            assert content is not None, "Empty compose file"
            assert "services" in content, "No services defined"
            print(f"\n✓ podman-compose.yml is valid YAML")
        except yaml.YAMLError as e:
            pytest.fail(f"Invalid YAML in podman-compose.yml: {e}")

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    def test_compose_defines_required_services(self):
        """Test that required services are defined in compose file."""
        content = yaml.safe_load(COMPOSE_FILE.read_text())
        services = content.get("services", {})

        required_services = ["weaviate", "neo4j", "redis", "rag-api"]
        missing_services = [s for s in required_services if s not in services]

        assert not missing_services, (
            f"Missing required services in podman-compose.yml: {missing_services}"
        )

        print(f"\n✓ All required services defined: {', '.join(required_services)}")

    def test_env_file_exists_or_example_exists(self):
        """Test that .env file exists or .env.example exists."""
        has_env = ENV_FILE.exists()
        has_example = (PROJECT_ROOT / ".env.example").exists()

        if not has_env and has_example:
            print(f"\n⚠ .env not found, but .env.example exists")
            print(f"  Create .env from .env.example before starting")
        elif has_env:
            print(f"\n✓ Found .env file")
        else:
            pytest.fail(".env file not found and no .env.example to copy from")


# ============================================================================
# Test: Podman Configuration
# ============================================================================

class TestPodmanConfiguration:
    """Verify Podman is properly configured."""

    def test_podman_running(self):
        """Test that Podman is running and accessible."""
        try:
            result = subprocess.run(
                ["podman", "info"],
                capture_output=True,
                timeout=5,
            )
            assert result.returncode == 0, (
                "Podman is not running or not accessible. "
                "Start podman service: systemctl --user start podman.socket"
            )
            print(f"\n✓ Podman is running")
        except subprocess.TimeoutExpired:
            pytest.fail("Podman command timed out")

    def test_podman_version_sufficient(self):
        """Test that Podman version is recent enough."""
        version_output = get_command_version("podman")

        # Just verify we got a version, don't enforce minimum
        # (different distros have different versions)
        assert "version" in version_output.lower(), (
            "Could not determine Podman version"
        )

        print(f"\n✓ Podman version: {version_output.split()[2] if len(version_output.split()) > 2 else 'unknown'}")

    def test_podman_socket_enabled(self):
        """Test that Podman socket is enabled (if using systemd)."""
        if not command_exists("systemctl"):
            pytest.skip("systemctl not available")

        try:
            result = subprocess.run(
                ["systemctl", "--user", "is-enabled", "podman.socket"],
                capture_output=True,
                timeout=5,
            )
            # enabled, disabled, or static are all ok
            # Just check that the service exists
            if result.returncode not in [0, 1]:
                print(f"\n⚠ podman.socket not found (may not be needed)")
            else:
                status = result.stdout.decode().strip()
                print(f"\n✓ podman.socket status: {status}")
        except subprocess.TimeoutExpired:
            pytest.skip("systemctl command timed out")


# ============================================================================
# Test: Python Environment
# ============================================================================

class TestPythonEnvironment:
    """Verify Python environment has required packages."""

    @pytest.mark.parametrize("package", [
        "weaviate",
        "neo4j",
        "redis",
        "fastapi",
        "langchain",
        "pydantic",
    ])
    def test_required_package_installed(self, package: str):
        """Test that required Python packages are installed."""
        try:
            __import__(package)
            print(f"\n✓ {package}: installed")
        except ImportError:
            pytest.fail(
                f"Required Python package '{package}' not installed. "
                f"Install dependencies: pip install -r requirements.txt"
            )

    def test_python_version_sufficient(self):
        """Test that Python version is 3.9 or higher."""
        import sys
        version = sys.version_info

        assert version >= (3, 9), (
            f"Python 3.9+ required, found {version.major}.{version.minor}"
        )

        print(f"\n✓ Python version: {version.major}.{version.minor}.{version.micro}")


# ============================================================================
# Test: Directory Structure
# ============================================================================

class TestDirectoryStructure:
    """Verify required directories exist."""

    def test_src_directory_exists(self):
        """Test that src/ directory exists."""
        src_dir = PROJECT_ROOT / "src"
        assert src_dir.exists() and src_dir.is_dir(), (
            "src/ directory not found"
        )
        print(f"\n✓ src/ directory exists")

    def test_data_directory_accessible(self):
        """Test that data/ directory exists or can be created."""
        data_dir = PROJECT_ROOT / "data"

        if not data_dir.exists():
            # Try to create it
            try:
                data_dir.mkdir(parents=True, exist_ok=True)
                print(f"\n✓ Created data/ directory")
            except Exception as e:
                pytest.fail(f"Cannot create data/ directory: {e}")
        else:
            print(f"\n✓ data/ directory exists")

    def test_volumes_directory_accessible(self):
        """Test that .volumes/ directory exists or can be created."""
        volumes_dir = PROJECT_ROOT / ".volumes"

        if not volumes_dir.exists():
            try:
                volumes_dir.mkdir(parents=True, exist_ok=True)
                print(f"\n✓ Created .volumes/ directory")
            except Exception as e:
                pytest.fail(f"Cannot create .volumes/ directory: {e}")
        else:
            print(f"\n✓ .volumes/ directory exists")


# ============================================================================
# Test: Port Availability
# ============================================================================

class TestPortAvailability:
    """Check that required ports are not already in use."""

    # Ports that will be used by the system
    REQUIRED_PORTS = [
        (8080, "Weaviate"),
        (7474, "Neo4j HTTP"),
        (7687, "Neo4j Bolt"),
        (6379, "Redis"),
        (8000, "RAG API"),
        (5555, "Open WebUI"),
    ]

    @pytest.mark.parametrize("port,service", REQUIRED_PORTS)
    def test_port_available(self, port: int, service: str):
        """Test that required port is not already in use."""
        if not check_port_available(port):
            print(f"\n⚠ Port {port} ({service}) is already in use")
            print(f"  This may be OK if services are already running")
            # Don't fail - just warn
        else:
            print(f"\n✓ Port {port} ({service}) is available")


# ============================================================================
# Test: System Resources
# ============================================================================

class TestSystemResources:
    """Check that system has sufficient resources."""

    def test_disk_space_available(self):
        """Test that sufficient disk space is available."""
        statvfs = os.statvfs(PROJECT_ROOT)

        # Available space in GB
        available_gb = (statvfs.f_bavail * statvfs.f_frsize) / (1024 ** 3)

        # Require at least 5GB free
        min_required_gb = 5

        if available_gb < min_required_gb:
            print(f"\n⚠ Low disk space: {available_gb:.1f}GB available")
            print(f"  Recommended: at least {min_required_gb}GB free")
        else:
            print(f"\n✓ Disk space: {available_gb:.1f}GB available")

        assert available_gb > 1, (
            f"Critically low disk space: {available_gb:.1f}GB. "
            f"Need at least 1GB to start."
        )

    def test_memory_available(self):
        """Test that sufficient memory is available."""
        try:
            with open('/proc/meminfo', 'r') as f:
                meminfo = f.read()

            # Parse MemAvailable
            for line in meminfo.split('\n'):
                if 'MemAvailable' in line:
                    available_kb = int(line.split()[1])
                    available_gb = available_kb / (1024 ** 2)

                    # Recommend at least 4GB available
                    min_recommended_gb = 4

                    if available_gb < min_recommended_gb:
                        print(f"\n⚠ Low memory: {available_gb:.1f}GB available")
                        print(f"  Recommended: at least {min_recommended_gb}GB available")
                    else:
                        print(f"\n✓ Memory: {available_gb:.1f}GB available")

                    # Only fail if critically low (< 1GB)
                    assert available_gb > 1, (
                        f"Critically low memory: {available_gb:.1f}GB. "
                        f"Need at least 1GB to start."
                    )
                    return

            pytest.skip("Could not determine available memory")
        except FileNotFoundError:
            pytest.skip("/proc/meminfo not available (not Linux?)")


# ============================================================================
# Summary Function
# ============================================================================

def print_preflight_summary():
    """Print a summary after all pre-flight checks pass."""
    print("\n" + "=" * 68)
    print("Pre-Flight Checks Summary")
    print("=" * 68)
    print()
    print("✓ All pre-flight checks passed")
    print()
    print("System is ready to start:")
    print("  - Required commands installed")
    print("  - Configuration files valid")
    print("  - Python environment ready")
    print("  - Podman configured")
    print("  - Sufficient resources available")
    print()
    print("=" * 68)
    print()


# ============================================================================
# Pytest Hooks
# ============================================================================

def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        'markers',
        'preflight: marks tests as pre-flight checks (deselect with "-m \'not preflight\'")'
    )


def pytest_sessionfinish(session, exitstatus):
    """Print summary after all tests complete."""
    if exitstatus == 0:
        print_preflight_summary()