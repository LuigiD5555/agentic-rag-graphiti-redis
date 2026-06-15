"""
Temporary file management utilities for document processing.
"""

import os
import tempfile
import shutil
from pathlib import Path
from typing import Optional, List
import atexit


class TempFileManager:
    """
    Manages temporary files and directories for document processing.
    """
    
    def __init__(self, base_dir: Optional[str] = None):
        """
        Initialize temp file manager.
        
        Args:
            base_dir: Base directory for temp files (default: system temp)
        """
        self.base_dir = Path(base_dir) if base_dir else Path(tempfile.gettempdir()) / "rag-work"
        self.created_paths: List[Path] = []
        
        # Ensure base directory exists
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
        # Register cleanup on exit
        atexit.register(self.cleanup)
    
    def create_temp_dir(self, prefix: str = "rag_") -> Path:
        """
        Create a temporary directory.
        
        Args:
            prefix: Directory name prefix
            
        Returns:
            Path to created directory
        """
        temp_dir = self.base_dir / f"{prefix}_{os.urandom(4).hex()}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        self.created_paths.append(temp_dir)
        return temp_dir
    
    def create_temp_file(self, suffix: str = "", prefix: str = "rag_") -> Path:
        """
        Create a temporary file.
        
        Args:
            suffix: File suffix (e.g., ".txt", ".pdf")
            prefix: File name prefix
            
        Returns:
            Path to created file
        """
        temp_file = self.base_dir / f"{prefix}_{os.urandom(4).hex()}{suffix}"
        temp_file.parent.mkdir(parents=True, exist_ok=True)
        temp_file.touch()
        self.created_paths.append(temp_file)
        return temp_file
    
    def ensure_temp_dir(self) -> Path:
        """
        Ensure the base temp directory exists.
        
        Returns:
            Path to base temp directory
        """
        self.base_dir.mkdir(parents=True, exist_ok=True)
        return self.base_dir
    
    def cleanup(self, keep_base: bool = True):
        """
        Clean up all created temporary files and directories.
        
        Args:
            keep_base: Whether to keep the base directory
        """
        for path in reversed(self.created_paths):
            try:
                if path.exists():
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        shutil.rmtree(path)
            except (OSError, PermissionError):
                # Ignore cleanup errors
                pass
        
        # Clear the list
        self.created_paths.clear()
        
        # Remove base directory if empty and not keeping it
        if not keep_base and self.base_dir.exists():
            try:
                # Check if directory is empty
                if not any(self.base_dir.iterdir()):
                    self.base_dir.rmdir()
            except (OSError, PermissionError):
                pass
    
    def get_temp_path(self, filename: str) -> Path:
        """
        Get a path in the temp directory for a specific filename.
        
        Args:
            filename: Name of the file
            
        Returns:
            Full path to the file
        """
        return self.base_dir / filename
    
    def file_exists(self, filename: str) -> bool:
        """
        Check if a file exists in the temp directory.
        
        Args:
            filename: Name of the file
            
        Returns:
            True if file exists
        """
        return (self.base_dir / filename).exists()


# Global instance for convenience
_temp_manager = TempFileManager()


def get_temp_manager() -> TempFileManager:
    """
    Get the global temp file manager instance.
    
    Returns:
        TempFileManager instance
    """
    return _temp_manager


def setup_temp_directory(work_dir: Optional[str] = None) -> Path:
    """
    Set up the temporary working directory.
    
    Args:
        work_dir: Custom work directory (default: /tmp/rag-work)
        
    Returns:
        Path to the work directory
    """
    if work_dir:
        work_path = Path(work_dir)
    else:
        work_path = Path("/tmp/rag-work")
    
    # Create directory with proper permissions
    work_path.mkdir(parents=True, exist_ok=True)
    
    # Set permissions (read/write for owner, read for group/others)
    work_path.chmod(0o755)
    
    # Update global temp manager
    global _temp_manager
    _temp_manager = TempFileManager(str(work_path))
    
    return work_path


def cleanup_temp_files():
    """
    Clean up all temporary files.
    """
    _temp_manager.cleanup()
