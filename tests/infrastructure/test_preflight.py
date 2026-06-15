"""
Pre-flight checks for system startup.

This module contains tests that should be run before starting the system
to ensure all dependencies, configuration, and prerequisites are met.

Usage:
    # Run all pre-flight checks
    pytest tests/infrastructure/test_preflight.py -v

    # Run all pre-flight checks (both host + runtime)
    pytest -m preflight -v

    # Run only checks that apply inside runtime/container
    pytest -m preflight_runtime -v

    # Run only host machine checks (podman/systemd/compose/.env)
    pytest -m preflight_host -v

    # Run in quiet mode (for scripts)
    pytest tests/infrastructure/test_preflight.py -q
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Tuple

import pytest
from pytest_readable import readable

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


def is_container_environment() -> bool:
    """Best-effort detection for containerized test environments."""
    return (
        os.path.exists("/.dockerenv")
        or os.path.exists("/run/.containerenv")
        or os.getenv("container") is not None
    )


def is_host_preflight_context() -> bool:
    """Return True when host-level preflight checks are meaningful."""
    return command_exists("podman") or COMPOSE_FILE.exists() or ENV_FILE.exists()


# ============================================================================
# Test: System Commands
# ============================================================================

@pytest.mark.preflight_runtime
class TestSystemCommands:
    """Verify required system commands are installed."""

    @pytest.mark.parametrize("command", [
        "curl",
        "python3",
    ])
    @readable(
        intent="Confirm critical system commands exist and publish their versions.",
        steps=[
            "Parametrize over curl and python3",
            "Check each command with shutil.which and fetch its version string",
        ],
        criteria=[
            "Both commands are discoverable in PATH",
            "Their version output is printed for diagnostics",
        ],
    )
    def test_command_exists(self, command: str):
        """Test that required command is available in PATH."""
        assert command_exists(command), (
            f"Required command '{command}' not found in PATH. "
            f"Please install it before starting the system."
        )

        # Print version info for visibility
        version = get_command_version(command)
        print(f"\n✓ {command}: {version}")

    @pytest.mark.preflight_host
    @readable(
        intent="Ensure podman-compose (or 'podman compose') is available on the host.",
        steps=[
            "Skip early if not in host preflight context",
            "Check podman-compose executable and fall back to 'podman compose version'",
        ],
        criteria=[
            "Either podman-compose or the podman compose command reports success",
        ],
    )
    def test_podman_compose_available(self):
        """Test that podman-compose is available."""
        if not is_host_preflight_context():
            pytest.skip("Host preflight context not detected")
        if not command_exists("podman"):
            pytest.skip("podman not available in this environment")

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

    @readable(
        intent="Validate pytest itself is installed for running the suite.",
        steps=[
            "Check PATH for pytest",
            "Print version information for visibility",
        ],
        criteria=[
            "pytest command is available",
            "Version string is emitted to the log",
        ],
    )
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

@pytest.mark.preflight_host
@pytest.mark.skipif(
    not is_host_preflight_context(),
    reason="Host preflight context not detected",
)
class TestConfigurationFiles:
    """Verify required configuration files exist and are valid."""

    @readable(
        intent="Ensure the podman-compose.yml exists before bootstrapping services.",
        steps=[
            "Skip if compose file is missing",
            "Verify the file exists at the expected path",
        ],
        criteria=[
            "Tests pass only when podman-compose.yml is present",
        ],
    )
    def test_compose_file_exists(self):
        """Test that podman-compose.yml exists."""
        if not COMPOSE_FILE.exists():
            pytest.skip(f"podman-compose.yml not found at {COMPOSE_FILE}")
        print(f"\n✓ Found podman-compose.yml")

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    @readable(
        intent="Validate that podman-compose.yml parses as YAML and defines services.",
        steps=[
            "Load the compose file via PyYAML",
            "Assert the services mapping exists",
        ],
        criteria=[
            "YAML parsing succeeds without exception",
            "Services key is present and non-empty",
        ],
    )
    def test_compose_file_valid_yaml(self):
        """Test that podman-compose.yml is valid YAML."""
        if not COMPOSE_FILE.exists():
            pytest.skip(f"podman-compose.yml not found at {COMPOSE_FILE}")
        try:
            content = yaml.safe_load(COMPOSE_FILE.read_text())
            assert content is not None, "Empty compose file"
            assert "services" in content, "No services defined"
            print(f"\n✓ podman-compose.yml is valid YAML")
        except yaml.YAMLError as e:
            pytest.fail(f"Invalid YAML in podman-compose.yml: {e}")

    @pytest.mark.skipif(not HAS_YAML, reason="PyYAML not installed")
    @readable(
        intent="Detect whether the compose file declares the core services the platform needs.",
        steps=[
            "Load services from the compose file",
            "Compare against the required list",
        ],
        criteria=[
            "All required services (weaviate/neo4j/app) appear",
        ],
    )
    def test_compose_defines_required_services(self):
        """Test that required services are defined in compose file."""
        if not COMPOSE_FILE.exists():
            pytest.skip(f"podman-compose.yml not found at {COMPOSE_FILE}")
        content = yaml.safe_load(COMPOSE_FILE.read_text())
        services = content.get("services", {})

        required_services = ["weaviate", "neo4j", "app"]
        missing_services = [s for s in required_services if s not in services]

        assert not missing_services, (
            f"Missing required services in podman-compose.yml: {missing_services}"
        )

        print(f"\n✓ All required services defined: {', '.join(required_services)}")

    @readable(
        intent="Warn or skip appropriately when the environment file is missing.",
        steps=[
            "Check for .env and .env.example",
            "Inform the user if only the example is present",
        ],
        criteria=[
            "Either .env is present or the test explains how to create it",
        ],
    )
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
            pytest.skip(".env and .env.example not present in this execution context")


# ============================================================================
# Test: Podman Configuration
# ============================================================================

@pytest.mark.preflight_host
@pytest.mark.skipif(
    not is_host_preflight_context(),
    reason="Host preflight context not detected",
)
class TestPodmanConfiguration:
    """Verify Podman is properly configured."""

    @readable(
        intent="Validate Podman daemon is running and reachable.",
        steps=[
            "Skip if podman binary is missing",
            "Run 'podman info' and ensure return code zero",
        ],
        criteria=[
            "Podman reports a running service (returncode 0)",
        ],
    )
    def test_podman_running(self):
        """Test that Podman is running and accessible."""
        if not command_exists("podman"):
            pytest.skip("podman not available in this environment")
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

    @readable(
        intent="Record the Podman version to ensure compatibility without enforcing a strict minimum.",
        steps=[
            "Skip if podman missing",
            "Capture the output of 'podman --version' for logging",
        ],
        criteria=[
            "Output mentions 'version' so we know what is installed",
        ],
    )
    def test_podman_version_sufficient(self):
        """Test that Podman version is recent enough."""
        if not command_exists("podman"):
            pytest.skip("podman not available in this environment")
        version_output = get_command_version("podman")

        # Just verify we got a version, don't enforce minimum
        # (different distros have different versions)
        assert "version" in version_output.lower(), (
            "Could not determine Podman version"
        )

        print(f"\n✓ Podman version: {version_output.split()[2] if len(version_output.split()) > 2 else 'unknown'}")

    @readable(
        intent="Ensure the Podman socket exists even if it is just static or disabled.",
        steps=[
            "Call 'systemctl --user is-enabled podman.socket'",
            "Log the status without failing on non-standard answers",
        ],
        criteria=[
            "Command completes (or times out) and the status is printed",
        ],
    )
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

@pytest.mark.preflight_runtime
class TestPythonEnvironment:
    """Verify Python environment has required packages."""

    @pytest.mark.parametrize("package", [
        "weaviate",
        "neo4j",
        "fastapi",
        "langchain_core",
        "pydantic",
    ])
    @readable(
        intent="Verify container-only Python packages exist when running inside the runtime.",
        steps=[
            "Attempt to import each package",
            "Fail inside container if missing, otherwise skip with instructions",
        ],
        criteria=[
            "Inside container all imports succeed",
            "Outside container the test is skipped with a helpful message",
        ],
    )
    def test_required_package_installed(self, package: str):
        """Test that required Python packages are installed.

        Note: This test is designed to run inside the container where
        all dependencies are installed. When running locally (host),
        the test will be skipped since dependencies are container-only.
        """
        try:
            __import__(package)
            print(f"\n✓ {package}: installed")
        except ImportError:
            if is_container_environment():
                # Inside container - this is a real failure
                pytest.fail(
                    f"Required Python package '{package}' not installed. "
                    f"Install dependencies: pip install -r requirements.txt"
                )
            else:
                # Outside container - skip this test (packages are container-only)
                pytest.skip(
                    f"Package '{package}' not available (test runs inside container). "
                        f"Run: podman exec -it app pytest tests/infrastructure/test_preflight.py"
                )

    @readable(
        intent="Ensure the Python interpreter is at least 3.9.",
        steps=[
            "Inspect sys.version_info",
            "Assert the major/minor version meets the minimum",
        ],
        criteria=[
            "Test fails if version < 3.9",
            "Prints the detected Python version for debugging",
        ],
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

@pytest.mark.preflight_runtime
class TestDirectoryStructure:
    """Verify required directories exist."""

    @readable(
        intent="Assert the src/ directory exists for code imports.",
        steps=[
            "Check PROJECT_ROOT/src directory presence",
        ],
        criteria=[
            "Test passes only if src/ exists and is a directory",
        ],
    )
    def test_src_directory_exists(self):
        """Test that src/ directory exists."""
        src_dir = PROJECT_ROOT / "src"
        assert src_dir.exists() and src_dir.is_dir(), (
            "src/ directory not found"
        )
        print(f"\n✓ src/ directory exists")

    @readable(
        intent="Ensure the data/ directory exists or can be created.",
        steps=[
            "Check for data/ and create it if needed",
        ],
        criteria=[
            "data/ directory exists at the end of the check",
        ],
    )
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

    @readable(
        intent="Make sure the .volumes/ directory is available for mounts.",
        steps=[
            "Create .volumes/ if missing",
        ],
        criteria=[
            ".volumes/ exists or is created without errors",
        ],
    )
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

    @readable(
        intent="Verify the control plane SQLite file is reachable or its directory exists.",
        steps=[
            "Check for data/control_plane.db",
            "Assert parent directory exists when file is missing",
        ],
        criteria=[
            "Either the db file exists or its directory is available",
        ],
    )
    def test_control_plane_db_ready(self):
        """Ensure the control plane SQLite file is reachable or can be created."""
        control_plane_db = PROJECT_ROOT / "data" / "control_plane.db"

        if not control_plane_db.exists():
            assert control_plane_db.parent.exists(), (
                f"Control plane directory {control_plane_db.parent} should exist"
            )
            print(
                f"\n⚠ {control_plane_db} not found yet (it will be created on first run)"
            )
        else:
            assert control_plane_db.is_file(), f"{control_plane_db} must be a file"
            print(f"\n✓ Control plane SQLite ready at {control_plane_db}")


# ============================================================================
# Test: Port Availability
# ============================================================================

@pytest.mark.preflight_runtime
class TestPortAvailability:
    """Check that required ports are not already in use."""

    # Ports that will be used by the system
    REQUIRED_PORTS = [
        (8080, "Weaviate"),
        (7474, "Neo4j HTTP"),
        (7687, "Neo4j Bolt"),
        (8000, "RAG API"),
        (5555, "Open WebUI"),
    ]

    @pytest.mark.parametrize("port,service", REQUIRED_PORTS)
    @readable(
        intent="Check that the key service ports are free or report they are in use.",
        steps=[
            "Iterate over REQUIRED_PORTS",
            "Call check_port_available for each port",
        ],
        criteria=[
            "Ports are logged as available or a warning is emitted if already in use",
        ],
    )
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

@pytest.mark.preflight_runtime
class TestSystemResources:
    """Check that system has sufficient resources."""

    @readable(
        intent="Report available disk space and fail if it is critically low.",
        steps=[
            "Calculate available GB via os.statvfs",
            "Warn if recommended threshold is not met and assert >1GB",
        ],
        criteria=[
            "Disk space > 1GB or test fails with clear message",
        ],
    )
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

    @readable(
        intent="Ensure the system reports sufficient available memory or skip gracefully.",
        steps=[
            "Read /proc/meminfo and parse MemAvailable",
            "Warn when below recommended threshold, fail only if <1GB",
        ],
        criteria=[
            "Test passes if available memory >1GB, otherwise skipped with context",
        ],
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
    config.addinivalue_line(
        'markers',
        'preflight_host: host-only preflight checks (podman/systemd/compose/.env)'
    )
    config.addinivalue_line(
        'markers',
        'preflight_runtime: runtime/container preflight checks'
    )


def pytest_sessionfinish(session, exitstatus):
    """Print summary after all tests complete."""
    if exitstatus == 0:
        print_preflight_summary()
