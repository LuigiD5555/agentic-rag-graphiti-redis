"""Manager for SQLite control plane repositories.

This module provides a centralized manager for accessing all SQLite repositories
and handles database initialization and configuration.
"""

import os
from pathlib import Path
from typing import Optional

from . import SQLiteControlPlane
from .repositories import (
    ScanCheckpointStore,
    FileMetadataStore,
    ChunkRegistryStore,
    SessionRepository,
    AuditRepository
)


class SQLiteControlPlaneManager:
    """Manager for SQLite control plane repositories."""
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize SQLite control plane manager.
        
        Args:
            db_path: Path to SQLite database file. If None, uses default path.
        """
        if db_path is None:
            # Default path: data/control_plane.db
            base_dir = Path(__file__).parent.parent.parent.parent.parent
            db_path = str(base_dir / "data" / "control_plane.db")
        
        self.db_path = db_path
        self.control_plane = SQLiteControlPlane(db_path)
        
        # Initialize repositories
        self.scan_checkpoint = ScanCheckpointStore(self.control_plane)
        self.file_metadata = FileMetadataStore(self.control_plane)
        self.chunk_registry = ChunkRegistryStore(self.control_plane)
        self.session_repo = SessionRepository(self.control_plane)
        self.audit_repo = AuditRepository(self.control_plane)
    
    def get_scan_checkpoint_store(self) -> ScanCheckpointStore:
        """Get scan checkpoint store."""
        return self.scan_checkpoint
    
    def get_file_metadata_store(self) -> FileMetadataStore:
        """Get file metadata store."""
        return self.file_metadata
    
    def get_chunk_registry_store(self) -> ChunkRegistryStore:
        """Get chunk registry store."""
        return self.chunk_registry
    
    def get_session_repository(self) -> SessionRepository:
        """Get session repository."""
        return self.session_repo
    
    def get_audit_repository(self) -> AuditRepository:
        """Get audit repository."""
        return self.audit_repo
    
    def cleanup_old_data(self, days_to_keep: int = 30) -> None:
        """
        Clean up old data from the database.
        
        Args:
            days_to_keep: Number of days of data to keep.
        """
        import time
        cutoff_time = int(time.time()) - (days_to_keep * 24 * 60 * 60)
        
        with self.control_plane.get_connection() as conn:
            # Delete old scan runs and related data
            conn.execute("""
                DELETE FROM scan_runs 
                WHERE updated_at < ? AND status IN ('COMPLETED', 'FAILED', 'CANCELLED')
            """, (cutoff_time,))
            
            # Delete old audit events
            conn.execute("""
                DELETE FROM audit_events WHERE event_at < ?
            """, (cutoff_time,))
            
            # Vacuum to reclaim space
            conn.execute("VACUUM")


# Global instance for easy access
_global_manager: Optional[SQLiteControlPlaneManager] = None
_global_manager_path: Optional[str] = None


def get_sqlite_manager(db_path: Optional[str] = None) -> SQLiteControlPlaneManager:
    """
    Get or create the global SQLite control plane manager.
    
    Args:
        db_path: Path to SQLite database file. If None, uses default path.
        
    Returns:
        SQLiteControlPlaneManager instance.
    """
    global _global_manager, _global_manager_path
    
    # Determine the actual path to use
    if db_path is None:
        # Default path: data/control_plane.db
        base_dir = Path(__file__).parent.parent.parent.parent.parent
        actual_path = str(base_dir / "data" / "control_plane.db")
    else:
        actual_path = db_path
    
    # Check if we need to create a new manager
    if _global_manager is None or _global_manager_path != actual_path:
        _global_manager = SQLiteControlPlaneManager(actual_path)
        _global_manager_path = actual_path
    
    return _global_manager


def init_sqlite_control_plane(db_path: Optional[str] = None) -> SQLiteControlPlaneManager:
    """
    Initialize SQLite control plane and return manager.
    
    This is an alias for get_sqlite_manager for backward compatibility.
    
    Args:
        db_path: Path to SQLite database file.
        
    Returns:
        SQLiteControlPlaneManager instance.
    """
    return get_sqlite_manager(db_path)