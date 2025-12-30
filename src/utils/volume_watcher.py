"""
Volume Watcher Service - Monitors external volumes and triggers actions when they reconnect.

This service runs in the background and periodically checks if volumes that were
previously unavailable have become accessible. When a volume reconnects, it can
trigger callbacks to handle the reconnection (e.g., re-scan directories).
"""

import os
import time
import threading
from typing import Callable, Dict, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass
class VolumeConfig:
    """Configuration for a monitored volume."""
    primary_path: str
    fallback_path: str
    name: str
    on_reconnect: Optional[Callable[[str], None]] = None


class VolumeWatcher:
    """
    Background service that watches for volume reconnections.

    This is useful for handling scenarios where external drives reconnect
    while the container is running.
    """

    def __init__(self, check_interval: int = 300):
        """
        Initialize the volume watcher.

        Args:
            check_interval: How often to check for volume changes (in seconds, default 5 minutes)
        """
        self.check_interval = check_interval
        self.volumes: Dict[str, VolumeConfig] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._volume_states: Dict[str, bool] = {}  # Track which volumes are using fallback

    def add_volume(
        self,
        primary_path: str,
        fallback_path: str,
        name: str,
        on_reconnect: Optional[Callable[[str], None]] = None
    ):
        """
        Add a volume to watch.

        Args:
            primary_path: The primary/preferred path for this volume
            fallback_path: The fallback path currently in use
            name: Human-readable name for logging
            on_reconnect: Optional callback to invoke when primary volume reconnects
        """
        config = VolumeConfig(
            primary_path=primary_path,
            fallback_path=fallback_path,
            name=name,
            on_reconnect=on_reconnect
        )

        self.volumes[name] = config

        # Check initial state
        is_using_fallback = self._is_using_fallback(primary_path, fallback_path)
        self._volume_states[name] = is_using_fallback

        if is_using_fallback:
            logger.info(
                f"Volume watcher: Monitoring '{name}' for reconnection. "
                f"Currently using fallback at {fallback_path}"
            )
        else:
            logger.info(
                f"Volume watcher: '{name}' is available at primary location {primary_path}"
            )

    def _is_using_fallback(self, primary_path: str, fallback_path: str) -> bool:
        """
        Check if a volume is currently using its fallback.

        Args:
            primary_path: Primary volume path
            fallback_path: Fallback volume path

        Returns:
            True if using fallback, False if using primary
        """
        # Check for fallback marker
        if os.path.exists(fallback_path):
            fallback_marker = os.path.join(fallback_path, ".using-fallback")
            if os.path.exists(fallback_marker):
                return True

        # Try to access primary
        try:
            if os.path.exists(primary_path):
                # Try a simple operation to verify it's accessible
                os.listdir(primary_path)
                return False
        except (OSError, PermissionError):
            pass

        return True

    def _check_primary_available(self, primary_path: str) -> bool:
        """
        Check if the primary volume has become available.

        Args:
            primary_path: Primary volume path to check

        Returns:
            True if primary is now available, False otherwise
        """
        try:
            if not os.path.exists(primary_path):
                return False

            # Try to list directory (this will fail if there's an I/O error)
            os.listdir(primary_path)

            # Check for the availability marker
            marker_path = os.path.join(primary_path, ".volume-available")
            return os.path.exists(marker_path)

        except (OSError, PermissionError) as e:
            logger.debug(f"Primary volume {primary_path} still not accessible: {e}")
            return False

    def _check_volumes(self):
        """Check all monitored volumes for reconnections."""
        for name, config in self.volumes.items():
            # Only check if we're currently using fallback
            if not self._volume_states.get(name, False):
                continue

            # Check if primary has become available
            if self._check_primary_available(config.primary_path):
                logger.info(
                    f"Volume '{name}' has RECONNECTED! "
                    f"Primary volume is now available at {config.primary_path}"
                )

                # Update state
                self._volume_states[name] = False

                # Trigger callback if provided
                if config.on_reconnect:
                    try:
                        logger.info(f"Triggering reconnect callback for '{name}'")
                        config.on_reconnect(config.primary_path)
                    except Exception as e:
                        logger.error(
                            f"Error in reconnect callback for '{name}': {e}",
                            exc_info=True
                        )

                # Log instructions for user
                logger.warning(
                    f"Volume '{name}' reconnected but container is using fallback mount. "
                    f"To use the primary volume, restart the container: "
                    f"podman-compose restart app"
                )

    def _watch_loop(self):
        """Main watch loop that runs in background thread."""
        logger.info(
            f"Volume watcher started. Checking every {self.check_interval} seconds."
        )

        while self._running:
            try:
                self._check_volumes()
            except Exception as e:
                logger.error(f"Error in volume watcher: {e}", exc_info=True)

            # Sleep in small intervals to allow quick shutdown
            for _ in range(self.check_interval):
                if not self._running:
                    break
                time.sleep(1)

        logger.info("Volume watcher stopped.")

    def start(self):
        """Start the background watcher thread."""
        if self._running:
            logger.warning("Volume watcher is already running")
            return

        if not self.volumes:
            logger.info("No volumes to watch, skipping volume watcher")
            return

        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True, name="VolumeWatcher")
        self._thread.start()
        logger.info("Volume watcher thread started")

    def stop(self):
        """Stop the background watcher thread."""
        if not self._running:
            return

        logger.info("Stopping volume watcher...")
        self._running = False

        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None

    def is_running(self) -> bool:
        """Check if the watcher is currently running."""
        return self._running


# Global watcher instance
_watcher: Optional[VolumeWatcher] = None


def get_watcher(check_interval: int = 300) -> VolumeWatcher:
    """
    Get or create the global volume watcher instance.

    Args:
        check_interval: How often to check volumes (in seconds, default 5 minutes)

    Returns:
        The global VolumeWatcher instance
    """
    global _watcher

    if _watcher is None:
        _watcher = VolumeWatcher(check_interval=check_interval)

    return _watcher


def setup_default_watchers(on_reconnect: Optional[Callable[[str], None]] = None):
    """
    Set up watchers for all external volumes from environment configuration.

    Args:
        on_reconnect: Optional callback when a volume reconnects
    """
    watcher = get_watcher()

    # Import here to avoid circular dependency
    from .volume_monitor import load_external_volumes_config

    # Load external volumes configuration
    volumes_config = load_external_volumes_config()

    volumes_added = 0
    for vol_config in volumes_config:
        name = vol_config.get("name")
        primary = vol_config.get("primary")
        mount_point = vol_config.get("mount")

        if not all([name, primary, mount_point]):
            logger.warning(f"Skipping incomplete volume config: {vol_config}")
            continue

        # Type guard - ensure all values are strings
        if not isinstance(name, str) or not isinstance(primary, str) or not isinstance(mount_point, str):
            logger.warning(f"Volume config has non-string values: {vol_config}")
            continue

        # Only set up if we're in a container (mount point exists)
        if not os.path.exists(mount_point):
            logger.debug(f"Mount point {mount_point} not found, skipping '{name}' volume watcher")
            continue

        logger.info(f"Setting up volume watcher for '{name}': {mount_point}")
        watcher.add_volume(
            primary_path=primary,
            fallback_path=mount_point,  # This is what container sees
            name=name,
            on_reconnect=on_reconnect
        )
        volumes_added += 1

    if volumes_added == 0:
        logger.debug("No external volumes found to watch, skipping volume watcher")
        return None

    # Start the watcher
    watcher.start()
    logger.info(f"Volume watcher started for {volumes_added} volume(s)")

    return watcher
