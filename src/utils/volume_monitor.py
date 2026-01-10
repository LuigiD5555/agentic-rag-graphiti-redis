"""
Volume Monitor - Detects when external volumes become available
This module monitors external volumes and can trigger re-scanning when they become available.
"""

import os
import time
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass
from src.rag.conf import Config

_config = Config()

logger = logging.getLogger(__name__)


@dataclass
class VolumeStatus:
    """Status of a monitored volume"""
    path: str
    is_available: bool
    is_fallback: bool
    last_check: float
    error_message: Optional[str] = None


class VolumeMonitor:
    """
    Monitors external volumes and detects when they become available.

    This is useful for handling scenarios where external drives may be temporarily
    unavailable (I/O errors, unmounted, etc.) and later reconnect.
    """

    def __init__(self, check_interval: int = 60):
        """
        Initialize the volume monitor.

        Args:
            check_interval: How often to check volumes (in seconds)
        """
        self.check_interval = check_interval
        self.volumes: Dict[str, VolumeStatus] = {}
        self._running = False

    def add_volume(self, primary_path: str, fallback_path: str, name: str = None):
        """
        Add a volume to monitor.

        Args:
            primary_path: The primary/preferred path for this volume
            fallback_path: The fallback path to use if primary is unavailable
            name: Human-readable name for logging
        """
        name = name or os.path.basename(primary_path)

        # Check initial status
        is_available, error = self._check_volume_availability(primary_path)

        if is_available:
            active_path = primary_path
            is_fallback = False
            logger.info(f"Volume '{name}' is available at: {primary_path}")
        else:
            active_path = fallback_path
            is_fallback = True
            logger.warning(
                f"Volume '{name}' is NOT available at {primary_path} ({error}). "
                f"Using fallback: {fallback_path}"
            )
            # Ensure fallback directory exists
            Path(fallback_path).mkdir(parents=True, exist_ok=True)

        self.volumes[name] = VolumeStatus(
            path=active_path,
            is_available=is_available,
            is_fallback=is_fallback,
            last_check=time.time(),
            error_message=error if not is_available else None
        )

    def _check_volume_availability(self, path: str) -> tuple[bool, Optional[str]]:
        """
        Check if a volume path is accessible.

        Args:
            path: Path to check

        Returns:
            Tuple of (is_available, error_message)
        """
        try:
            # Try to list the directory with a timeout
            # This will fail if there's an I/O error or the mount is stale
            if not os.path.exists(path):
                return False, "Path does not exist"

            # Try to perform an actual I/O operation
            test_entries = os.listdir(path)

            # If we can read it, check for the availability marker
            marker_path = os.path.join(path, ".volume-available")
            has_marker = os.path.exists(marker_path)

            return True, None

        except OSError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Unexpected error: {str(e)}"

    def check_volumes(self) -> Dict[str, bool]:
        """
        Check all monitored volumes and update their status.

        Returns:
            Dictionary mapping volume names to whether they changed status
        """
        changes = {}

        for name, status in self.volumes.items():
            # Only check if using fallback
            if not status.is_fallback:
                changes[name] = False
                continue

            # Extract the primary path (we need to track it separately)
            # For now, we'll assume the primary path is stored elsewhere
            # In a real implementation, you'd want to store both paths

            changes[name] = False
            status.last_check = time.time()

        return changes

    def get_active_paths(self) -> Dict[str, str]:
        """
        Get the currently active paths for all volumes.

        Returns:
            Dictionary mapping volume names to their active paths
        """
        return {name: status.path for name, status in self.volumes.items()}

    def is_using_fallback(self, name: str) -> bool:
        """
        Check if a volume is currently using its fallback path.

        Args:
            name: Volume name

        Returns:
            True if using fallback, False if using primary
        """
        if name not in self.volumes:
            raise ValueError(f"Volume '{name}' is not being monitored")

        return self.volumes[name].is_fallback

    def get_status(self, name: str) -> Optional[VolumeStatus]:
        """Get the status of a specific volume."""
        return self.volumes.get(name)

    def get_all_statuses(self) -> Dict[str, VolumeStatus]:
        """Get statuses of all monitored volumes."""
        return self.volumes.copy()


def detect_volume_type(path: str) -> str:
    """
    Detect if a path is using a fallback directory.

    Args:
        path: Path to check

    Returns:
        "primary" if using primary volume, "fallback" if using fallback
    """
    fallback_marker = os.path.join(path, ".using-fallback")

    if os.path.exists(fallback_marker):
        return "fallback"

    return "primary"


def get_available_sources() -> List[str]:
    """
    Get list of available document sources by checking mounted volumes.

    This function checks both primary and fallback paths and returns
    all accessible directories.

    Returns:
        List of accessible source paths
    """
    sources = []

    # Check Libros directory
    libros_path = os.environ.get("DOCS_PATH", "/mnt/Documents/Documents")
    libros_external = "/mnt/resources/Libros"

    # Always add main docs path
    if os.path.exists(libros_path):
        sources.append(libros_path)

    # Add external Libros if available
    if os.path.exists(libros_external):
        volume_type = detect_volume_type(libros_external)
        if volume_type == "fallback":
            logger.info(f"Using fallback directory for Libros: {libros_external}")
        sources.append(libros_external)

    return sources


# Global monitor instance
_monitor: Optional[VolumeMonitor] = None


def load_external_volumes_config() -> List[Dict[str, str]]:
    """
    Load external volumes configuration with priority:
    1. settings.json (user-editable, persistent)
    2. EXTERNAL_VOLUMES env var
    3. Legacy HOST_LIBROS_DIR

    Returns:
        List of volume configurations, each with 'name', 'primary', 'fallback', 'mount'
    """
    # Priority 1: Check settings.json
    try:
        import src.settings as settings

        if hasattr(settings, 'EXTERNAL_VOLUMES') and settings.EXTERNAL_VOLUMES:
            volumes = settings.EXTERNAL_VOLUMES
            if isinstance(volumes, list):
                logger.info(f"Loaded {len(volumes)} external volume(s) from settings.json")
                return volumes
            else:
                logger.warning(f"EXTERNAL_VOLUMES in settings.json is not a list: {type(volumes)}")
    except Exception as e:
        logger.debug(f"Could not load EXTERNAL_VOLUMES from settings: {e}")

    # Priority 2: Check EXTERNAL_VOLUMES environment variable
    config_str = os.environ.get("EXTERNAL_VOLUMES", "")
    if config_str:
        try:
            volumes = json.loads(config_str)
            if not isinstance(volumes, list):
                logger.error(f"EXTERNAL_VOLUMES env var must be a JSON array, got: {type(volumes)}")
            else:
                logger.info(f"Loaded {len(volumes)} external volume(s) from EXTERNAL_VOLUMES env var")
                return volumes
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse EXTERNAL_VOLUMES JSON from env: {e}")

    libros_primary = os.environ.get("HOST_LIBROS_DIR", "/mnt/resources/Libros")
    libros_fallback = os.environ.get("FALLBACK_LIBROS_DIR", "./data/libros-fallback")
    logger.info("Using Libros configuration from env vars")
    return [{
        "name": "Libros",
        "primary": libros_primary,
        "fallback": libros_fallback,
        "mount": "/mnt/resources/Libros"
    }]


def get_monitor() -> VolumeMonitor:
    """Get or create the global volume monitor instance."""
    global _monitor

    if _monitor is None:
        _monitor = VolumeMonitor()

        # Load external volumes from configuration
        volumes_config = load_external_volumes_config()

        for vol_config in volumes_config:
            name = vol_config.get("name")
            primary = vol_config.get("primary")
            fallback = vol_config.get("fallback")
            mount_point = vol_config.get("mount")

            if not all([name, primary, fallback, mount_point]):
                logger.warning(f"Skipping incomplete volume config: {vol_config}")
                continue

            # Only monitor if we're inside a container (check if mount point exists)
            if os.path.exists(mount_point):
                logger.info(f"Adding volume monitor for '{name}': {primary} -> {mount_point}")
                _monitor.add_volume(
                    primary_path=mount_point,  # Inside container, we see the mount point
                    fallback_path=fallback,
                    name=name
                )

    return _monitor