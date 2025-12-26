"""Artifact manager for storing and cleaning tool outputs with TTL."""
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ArtifactManager:
    """Manages artifacts (PDFs, images, extracted archives) with TTL cleanup.

    Artifacts are stored in /tmp/artifacts/{thread_id}/ and cleaned
    up automatically after TTL expires.
    """

    def __init__(
        self,
        base_dir: Optional[str] = None,
        ttl_hours: int = 48
    ):
        """Initialize artifact manager.

        Args:
            base_dir: Base directory for artifacts (default: /tmp/artifacts)
            ttl_hours: Time-to-live in hours (default: 48)
        """
        self.base_dir = Path(base_dir or os.getenv(
            "ARTIFACTS_BASE_DIR",
            "/tmp/artifacts"
        ))
        self.ttl_hours = ttl_hours
        self.ttl_seconds = ttl_hours * 3600

        # Ensure base dir exists
        self.base_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"ArtifactManager initialized: base_dir={self.base_dir}, "
            f"ttl={ttl_hours}h"
        )

    def get_thread_dir(self, thread_id: str) -> Path:
        """Get artifact directory for a thread.

        Args:
            thread_id: Thread identifier

        Returns:
            Path to thread's artifact directory
        """
        thread_dir = self.base_dir / f"thread-{thread_id[:16]}"
        thread_dir.mkdir(parents=True, exist_ok=True)
        return thread_dir

    def store_artifact(
        self,
        thread_id: str,
        source_path: str,
        filename: Optional[str] = None
    ) -> str:
        """Store artifact for a thread.

        Args:
            thread_id: Thread identifier
            source_path: Path to source file to copy
            filename: Optional custom filename (defaults to source basename)

        Returns:
            Path to stored artifact

        Raises:
            FileNotFoundError: If source_path doesn't exist
            IOError: If copy fails
        """
        source = Path(source_path)
        if not source.exists():
            raise FileNotFoundError(f"Source file not found: {source_path}")

        # Determine filename
        if filename is None:
            filename = source.name

        # Get thread directory
        thread_dir = self.get_thread_dir(thread_id)

        # Copy artifact
        dest = thread_dir / filename
        shutil.copy2(source, dest)

        logger.info(
            f"Stored artifact: {filename} for thread {thread_id[:8]}... "
            f"({dest.stat().st_size} bytes)"
        )

        return str(dest)

    def store_artifact_data(
        self,
        thread_id: str,
        data: bytes,
        filename: str
    ) -> str:
        """Store artifact from bytes data.

        Args:
            thread_id: Thread identifier
            data: File data as bytes
            filename: Filename for artifact

        Returns:
            Path to stored artifact
        """
        thread_dir = self.get_thread_dir(thread_id)
        dest = thread_dir / filename

        dest.write_bytes(data)

        logger.info(
            f"Stored artifact data: {filename} for thread {thread_id[:8]}... "
            f"({len(data)} bytes)"
        )

        return str(dest)

    def get_artifact(
        self,
        thread_id: str,
        filename: str
    ) -> Optional[bytes]:
        """Retrieve artifact for a thread.

        Args:
            thread_id: Thread identifier
            filename: Filename to retrieve

        Returns:
            File data as bytes, or None if not found/expired
        """
        thread_dir = self.base_dir / f"thread-{thread_id[:16]}"
        artifact = thread_dir / filename

        if not artifact.exists():
            return None

        # Check if expired
        age = time.time() - artifact.stat().st_mtime
        if age > self.ttl_seconds:
            logger.debug(f"Artifact expired: {filename} (age: {age/3600:.1f}h)")
            return None

        return artifact.read_bytes()

    def list_artifacts(self, thread_id: str) -> list[str]:
        """List all artifacts for a thread.

        Args:
            thread_id: Thread identifier

        Returns:
            List of artifact filenames
        """
        thread_dir = self.base_dir / f"thread-{thread_id[:16]}"

        if not thread_dir.exists():
            return []

        return [f.name for f in thread_dir.iterdir() if f.is_file()]

    def cleanup_thread(self, thread_id: str) -> int:
        """Clean up all artifacts for a thread.

        Args:
            thread_id: Thread identifier

        Returns:
            Number of files deleted
        """
        thread_dir = self.base_dir / f"thread-{thread_id[:16]}"

        if not thread_dir.exists():
            return 0

        count = 0
        for item in thread_dir.iterdir():
            if item.is_file():
                item.unlink()
                count += 1
            elif item.is_dir():
                shutil.rmtree(item)
                count += 1

        # Remove thread directory if empty
        try:
            thread_dir.rmdir()
        except OSError:
            pass

        logger.info(f"Cleaned up {count} items for thread {thread_id[:8]}...")
        return count

    def cleanup_expired(self) -> int:
        """Clean up all expired artifacts across all threads.

        This is the main cleanup method called by systemd timer.

        Returns:
            Number of items deleted
        """
        if not self.base_dir.exists():
            return 0

        count = 0
        current_time = time.time()

        for thread_dir in self.base_dir.iterdir():
            if not thread_dir.is_dir():
                continue

            # Check each artifact
            thread_empty = True
            for artifact in thread_dir.iterdir():
                try:
                    age = current_time - artifact.stat().st_mtime

                    if age > self.ttl_seconds:
                        # Expired
                        if artifact.is_file():
                            artifact.unlink()
                            count += 1
                            logger.debug(
                                f"Deleted expired artifact: {artifact.name} "
                                f"(age: {age/3600:.1f}h)"
                            )
                        elif artifact.is_dir():
                            shutil.rmtree(artifact)
                            count += 1
                            logger.debug(
                                f"Deleted expired directory: {artifact.name}"
                            )
                    else:
                        thread_empty = False
                except Exception as e:
                    logger.error(f"Error cleaning {artifact}: {e}")
                    thread_empty = False

            # Remove thread directory if empty
            if thread_empty:
                try:
                    thread_dir.rmdir()
                    logger.debug(f"Removed empty thread dir: {thread_dir.name}")
                except OSError:
                    pass

        logger.info(f"Cleanup completed: {count} items deleted")
        return count

    def get_stats(self) -> dict:
        """Get artifact storage statistics.

        Returns:
            Dict with stats (total_threads, total_files, total_size_mb)
        """
        if not self.base_dir.exists():
            return {"total_threads": 0, "total_files": 0, "total_size_mb": 0.0}

        total_threads = 0
        total_files = 0
        total_size = 0

        for thread_dir in self.base_dir.iterdir():
            if not thread_dir.is_dir():
                continue

            total_threads += 1

            for artifact in thread_dir.rglob("*"):
                if artifact.is_file():
                    total_files += 1
                    total_size += artifact.stat().st_size

        return {
            "total_threads": total_threads,
            "total_files": total_files,
            "total_size_mb": total_size / (1024 * 1024)
        }


def create_artifact_manager(
    base_dir: Optional[str] = None,
    ttl_hours: int = 48
) -> ArtifactManager:
    """Factory function to create artifact manager.

    Args:
        base_dir: Optional base directory override
        ttl_hours: Optional TTL override

    Returns:
        Configured ArtifactManager instance
    """
    return ArtifactManager(base_dir=base_dir, ttl_hours=ttl_hours)