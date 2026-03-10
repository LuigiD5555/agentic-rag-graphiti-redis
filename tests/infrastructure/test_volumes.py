"""
Volume verification tests for external storage volumes.

This test module verifies that external volumes are accessible and sets up
fallback directories when they are not. It replaces the old check-volumes.sh
bash script with a proper Python test.

Usage:
    # Run volume checks only
    pytest tests/infrastructure/test_volumes.py -v

    # Run with infrastructure marker
    pytest -m infrastructure -v

    # Run and setup fallbacks (use --setup-fallback flag in conftest)
    pytest tests/infrastructure/test_volumes.py --setup-fallback -v
"""

import os
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Tuple, List, Dict

import pytest
from dotenv import load_dotenv, set_key
from pytest_readable import readable


# ============================================================================
# Pytest Markers
# ============================================================================

pytestmark = [
    pytest.mark.infrastructure,
    pytest.mark.volumes,
]


# ============================================================================
# Configuration
# ============================================================================

class VolumeConfig:
    """Configuration for volume paths and fallbacks."""

    def __init__(self):
        """Load configuration from environment."""
        # Load .env file
        env_path = Path(__file__).parents[2] / '.env'
        if env_path.exists():
            load_dotenv(env_path)

        self.env_path = env_path
        self.project_root = Path(__file__).parents[2]

        # Load external volumes from EXTERNAL_VOLUMES env var
        self.volumes = self._load_external_volumes()

        libros_config = next((vol for vol in self.volumes if vol.get('name') == 'Libros'), None)
        if libros_config:
            self.host_libros_dir = libros_config['primary']
            self.fallback_libros_dir = Path(libros_config['fallback'])
        else:
            self.host_libros_dir = os.getenv("HOST_LIBROS_DIR", "/mnt/resources/Libros")
            self.fallback_libros_dir = Path(
                self.project_root / os.getenv("FALLBACK_LIBROS_DIR", "data/libros-fallback")
            )

    def _load_external_volumes(self) -> List[Dict[str, str]]:
        """
        Load external volumes configuration from EXTERNAL_VOLUMES env var.

        Returns:
            List of volume configurations with 'name', 'primary', 'fallback', 'mount'
        """
        config_str = os.getenv("EXTERNAL_VOLUMES", "")

        if not config_str:
            libros_primary = os.getenv("HOST_LIBROS_DIR", "/mnt/resources/Libros")
            libros_fallback = os.getenv("FALLBACK_LIBROS_DIR", "data/libros-fallback")
            return [{
                "name": "Libros",
                "primary": libros_primary,
                "fallback": str(self.project_root / libros_fallback),
                "mount": "/mnt/resources/Libros"
            }]

        try:
            volumes = json.loads(config_str)
            if not isinstance(volumes, list):
                print(f"ERROR: EXTERNAL_VOLUMES must be a JSON array, got: {type(volumes)}")
                return []

            # Resolve relative fallback paths
            for vol in volumes:
                fallback = vol.get('fallback', '')
                if not os.path.isabs(fallback):
                    vol['fallback'] = str(self.project_root / fallback)

            return volumes
        except json.JSONDecodeError as e:
            print(f"ERROR: Failed to parse EXTERNAL_VOLUMES JSON: {e}")
            return []


# ============================================================================
# Volume Checker Class
# ============================================================================

class VolumeChecker:
    """Handles volume verification and fallback setup."""

    def __init__(self, config: VolumeConfig):
        """Initialize with configuration."""
        self.config = config

    def check_volume_accessible(self, path: str, timeout: int = 2) -> bool:
        """
        Check if a volume path is accessible.

        Args:
            path: Path to check
            timeout: Timeout in seconds for the check

        Returns:
            True if accessible, False otherwise
        """
        try:
            # Use timeout command to avoid hanging on I/O errors
            result = subprocess.run(
                ['timeout', str(timeout), 'ls', path],
                capture_output=True,
                timeout=timeout + 1,  # Extra second for subprocess timeout
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

    def setup_fallback_directory(
        self,
        fallback_path: Path,
        primary_path: str,
    ) -> None:
        """
        Create fallback directory with marker file.

        Args:
            fallback_path: Path to fallback directory
            primary_path: Path to the primary volume (for documentation)
        """
        # Create fallback directory
        fallback_path.mkdir(parents=True, exist_ok=True)

        # Create marker file
        marker_content = f"""This is a fallback directory because the primary volume at:
  {primary_path}
was not accessible at container startup.

Timestamp: {datetime.now().isoformat()}

To restore primary volume:
1. Fix the mount issue (reconnect drive, fix I/O error, etc.)
2. Restart the container - it will automatically detect and use the primary volume
"""
        marker_file = fallback_path / '.using-fallback'
        marker_file.write_text(marker_content)

    def mark_volume_available(self, path: str) -> None:
        """
        Mark a volume as available by creating a marker file.

        Args:
            path: Volume path to mark as available
        """
        volume_path = Path(path)
        volume_path.mkdir(parents=True, exist_ok=True)
        marker_file = volume_path / '.volume-available'
        marker_file.touch()

    def remove_fallback_marker(self, fallback_path: Path) -> None:
        """
        Remove fallback marker if it exists.

        Args:
            fallback_path: Path to fallback directory
        """
        marker_file = fallback_path / '.using-fallback'
        if marker_file.exists():
            marker_file.unlink()

    def check_and_setup_libros_volume(self, setup_fallback: bool = True) -> Tuple[str, bool]:
        """
        Check Libros volume and setup fallback if needed.

        Args:
            setup_fallback: Whether to create fallback directory if volume is not accessible

        Returns:
            Tuple of (active_path, is_primary)
        """
        primary_path = self.config.host_libros_dir
        fallback_path = self.config.fallback_libros_dir

        # Check if primary volume is accessible
        if self.check_volume_accessible(primary_path):
            # Mark as available
            self.mark_volume_available(primary_path)

            # Remove fallback marker if it exists
            if fallback_path.exists():
                self.remove_fallback_marker(fallback_path)

            return primary_path, True
        else:
            # Primary volume not accessible
            if setup_fallback:
                self.setup_fallback_directory(fallback_path, primary_path)
                return str(fallback_path), False
            else:
                return primary_path, False

    def update_env_file(self, active_libros_dir: str) -> None:
        """
        Update .env file with active volume path.

        Args:
            active_libros_dir: The active directory path to save
        """
        env_path = self.config.env_path

        if env_path.exists():
            # Update or add ACTIVE_LIBROS_DIR
            set_key(
                env_path,
                'ACTIVE_LIBROS_DIR',
                active_libros_dir,
                quote_mode='never'
            )
        else:
            # Create new .env file
            env_path.write_text(f'ACTIVE_LIBROS_DIR={active_libros_dir}\n')


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def volume_config():
    """Provide volume configuration."""
    return VolumeConfig()


@pytest.fixture
def volume_checker(volume_config):
    """Provide volume checker instance."""
    return VolumeChecker(volume_config)


@pytest.fixture
def setup_fallback(request):
    """Determine if fallback setup should be performed."""
    return request.config.getoption('--setup-fallback', default=False)


# ============================================================================
# Tests
# ============================================================================

class TestVolumeAccessibility:
    """Tests for volume accessibility checks."""

    @readable(
        intent="Check whether the Libros volume path is reachable and log the result.",
        steps=[
            "Call VolumeChecker.check_volume_accessible with host Libros directory",
            "Assert the return type is boolean and log the access state",
        ],
        criteria=[
            "Test always returns a bool even if the volume is missing",
        ],
    )
    def test_libros_volume_check(self, volume_checker, volume_config):
        """Test that we can check if Libros volume is accessible."""
        result = volume_checker.check_volume_accessible(
            volume_config.host_libros_dir
        )

        # Result should be a boolean
        assert isinstance(result, bool)

        # Print result for visibility
        if result:
            print(f"\n✓ Libros volume is accessible: {volume_config.host_libros_dir}")
        else:
            print(f"\n⚠ Libros volume is NOT accessible: {volume_config.host_libros_dir}")

    @readable(
        intent="Ensure volume checks handle missing paths without hanging.",
        steps=[
            "Call check_volume_accessible on a path that doesn't exist",
            "Assert the function returns False rather than raising",
        ],
        criteria=[
            "Timeout handling gracefully returns False",
        ],
    )
    def test_volume_timeout_handling(self, volume_checker):
        """Test that volume checks handle timeouts properly."""
        # This should timeout quickly for non-existent paths
        result = volume_checker.check_volume_accessible(
            '/definitely/does/not/exist/path/12345',
            timeout=1
        )

        # Should return False (not raise an exception)
        assert result is False


class TestFallbackSetup:
    """Tests for fallback directory setup."""

    @readable(
        intent="Verify fallback directories and marker files are created correctly.",
        steps=[
            "Create a temporary fallback path",
            "Invoke setup_fallback_directory and inspect the marker file content",
        ],
        criteria=[
            "Fallback directory and .using-fallback marker exist",
            "Marker text references the primary path",
        ],
    )
    def test_fallback_directory_creation(self, volume_checker, volume_config, tmp_path):
        """Test that fallback directory is created correctly."""
        # Use tmp_path for testing
        test_fallback = tmp_path / 'test-fallback'
        test_primary = '/mnt/test/primary'

        # Setup fallback
        volume_checker.setup_fallback_directory(test_fallback, test_primary)

        # Verify directory was created
        assert test_fallback.exists()
        assert test_fallback.is_dir()

        # Verify marker file was created
        marker_file = test_fallback / '.using-fallback'
        assert marker_file.exists()

        # Verify marker content
        content = marker_file.read_text()
        assert test_primary in content
        assert 'fallback directory' in content.lower()

    @readable(
        intent="Ensure the '.volume-available' marker is created for accessible volumes.",
        steps=[
            "Call mark_volume_available on a temporary path",
            "Assert the marker file exists",
        ],
        criteria=[
            "Marker file is created even if volume path is artificial",
        ],
    )
    def test_volume_marker_creation(self, volume_checker, tmp_path):
        """Test that volume available marker is created."""
        test_volume = tmp_path / 'test-volume'

        # Mark volume as available
        volume_checker.mark_volume_available(str(test_volume))

        # Verify marker was created
        marker_file = test_volume / '.volume-available'
        assert marker_file.exists()

    @readable(
        intent="Assert that fallback markers are removed when they are no longer needed.",
        steps=[
            "Create a '.using-fallback' marker",
            "Call remove_fallback_marker and ensure the file disappears",
        ],
        criteria=[
            "Marker file is deleted without raising errors",
        ],
    )
    def test_fallback_marker_removal(self, volume_checker, tmp_path):
        """Test that fallback marker is removed correctly."""
        test_fallback = tmp_path / 'test-fallback'
        test_fallback.mkdir()

        # Create fallback marker
        marker_file = test_fallback / '.using-fallback'
        marker_file.write_text('test marker')

        # Remove marker
        volume_checker.remove_fallback_marker(test_fallback)

        # Verify marker was removed
        assert not marker_file.exists()


class TestVolumeIntegration:
    """Integration tests for full volume check and setup workflow."""

    @readable(
        intent="Drive the Libros volume check and update fallback settings when requested.",
        steps=[
            "Run check_and_setup_libros_volume with the setup flag",
            "Verify the returned active path and fallback flag types",
            "Update .env if fallback setup occurred",
        ],
        criteria=[
            "Active path is not None and is_primary is a bool",
            "No exceptions occur when setup_fallback toggles fallback behavior",
        ],
    )
    def test_libros_volume_with_fallback_setup(
        self,
        volume_checker,
        volume_config,
        setup_fallback,
    ):
        """Test Libros volume check and setup fallback if needed."""
        # Check and setup
        active_path, is_primary = volume_checker.check_and_setup_libros_volume(
            setup_fallback=setup_fallback
        )

        # Verify we got valid results
        assert active_path is not None
        assert isinstance(is_primary, bool)

        # Update .env file with active path
        if setup_fallback:
            volume_checker.update_env_file(active_path)

        # Print summary
        print("\n" + "=" * 68)
        print("Volume Check Summary")
        print("=" * 68)
        print()

        if is_primary:
            print("✓ All volumes are accessible")
            print()
            print("Primary volumes in use:")
            print(f"  - Libros: {active_path}")
        else:
            print("⚠ Using fallback directories" if setup_fallback else "⚠ Primary volume not accessible")
            print()
            print("Active directories:")
            print(f"  - Libros: {active_path}" + (" (FALLBACK)" if setup_fallback else " (NOT ACCESSIBLE)"))

            if setup_fallback:
                print()
                print("Note: Containers will start successfully using fallback directories.")
                print("      Once you fix the volume issues, restart containers to use primary volumes.")

        print()
        print("Volume check complete." + (" Safe to start containers." if setup_fallback or is_primary else ""))
        print()

        # If we're in setup mode, this should not fail
        if setup_fallback:
            assert active_path is not None
        else:
            # In check-only mode, we just verify we can check
            assert isinstance(is_primary, bool)

    @readable(
        intent="Ensure the .env file records the active Libros path without duplication.",
        steps=[
            "Instantiate VolumeChecker pointing at a temporary .env",
            "Update the file twice with different paths and inspect content",
        ],
        criteria=[
            "Only one ACTIVE_LIBROS_DIR entry exists",
            "The second update replaces the first path",
        ],
    )
    def test_env_file_update(self, volume_checker, tmp_path):
        """Test that .env file is updated correctly."""
        # Create temporary config with test .env path
        test_env = tmp_path / '.env'
        test_config = VolumeConfig()
        test_config.env_path = test_env

        test_checker = VolumeChecker(test_config)

        # Update env file
        test_path = '/test/path/libros'
        test_checker.update_env_file(test_path)

        # Verify file was created
        assert test_env.exists()

        # Verify content
        content = test_env.read_text()
        assert 'ACTIVE_LIBROS_DIR' in content
        assert test_path in content

        # Update again with different path
        new_path = '/new/test/path'
        test_checker.update_env_file(new_path)

        # Verify it was updated (not duplicated)
        content = test_env.read_text()
        assert content.count('ACTIVE_LIBROS_DIR') == 1
        assert new_path in content
        assert test_path not in content
