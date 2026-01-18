"""
Dynamic Path Manager for RAG System

This module provides functions to dynamically manage document paths at runtime,
allowing users to add, remove, and list paths without restarting the system.
Paths are persisted to data/settings.json for persistence across restarts.
"""

import os
import json
import logging
from pathlib import Path
from typing import List, Set, Optional
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class PathEntry:
    """Represents a document path entry."""
    path: str
    enabled: bool = True
    description: str = ""
    
    def to_dict(self):
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict):
        return cls(**data)


class PathManager:
    """
    Manages document paths dynamically at runtime.
    
    This class provides methods to:
    1. Add new document paths
    2. Remove existing paths
    3. Enable/disable paths
    4. List all paths
    5. Persist changes to settings.json
    """
    
    def __init__(self, settings_file: Optional[str] = None):
        """
        Initialize the path manager.
        
        Args:
            settings_file: Path to settings.json file. If None, uses default location.
        """
        if settings_file is None:
            # Default to data/settings.json relative to project root
            project_root = Path(__file__).parent.parent.parent
            self.settings_file = project_root / "data" / "settings.json"
        else:
            self.settings_file = Path(settings_file)
        
        self._paths: List[PathEntry] = []
        self._load_paths()
    
    def _load_paths(self) -> None:
        """Load paths from settings.json file."""
        try:
            if self.settings_file.exists():
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                
                # Load from DOCS_PATHS array
                docs_paths = settings.get('DOCS_PATHS', [])
                for path in docs_paths:
                    if isinstance(path, str):
                        self._paths.append(PathEntry(path=path, enabled=True))
                    elif isinstance(path, dict):
                        self._paths.append(PathEntry.from_dict(path))
                
                logger.info(f"Loaded {len(self._paths)} document paths from {self.settings_file}")
            else:
                logger.warning(f"Settings file not found: {self.settings_file}")
                # Initialize with default paths
                self._paths = [
                    PathEntry(path="/mnt/Documents/Documents", enabled=True, description="Main documents directory"),
                    PathEntry(path="/mnt/resources/Libros/Aprendizaje", enabled=True, description="Books directory")
                ]
                self._save_paths()
                
        except Exception as e:
            logger.error(f"Failed to load paths from {self.settings_file}: {e}")
            # Fallback to empty list
            self._paths = []
    
    def _save_paths(self) -> bool:
        """Save paths to settings.json file."""
        try:
            # Load existing settings
            settings = {}
            if self.settings_file.exists():
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
            
            # Convert paths to simple list for backward compatibility
            # We store as strings for compatibility with existing code
            docs_paths = []
            for entry in self._paths:
                if entry.enabled:
                    docs_paths.append(entry.path)
            
            # Update settings
            settings['DOCS_PATHS'] = docs_paths
            
            # Save back to file
            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(settings, f, indent=2, ensure_ascii=False)
            
            logger.info(f"Saved {len(docs_paths)} document paths to {self.settings_file}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to save paths to {self.settings_file}: {e}")
            return False
    
    def add_path(self, path: str, description: str = "", enable: bool = True) -> bool:
        """
        Add a new document path.
        
        Args:
            path: The filesystem path to add
            description: Optional description of the path
            enable: Whether to enable the path immediately
            
        Returns:
            True if path was added successfully, False otherwise
        """
        # Normalize path
        normalized_path = os.path.abspath(path) if os.path.isabs(path) else path
        
        # Check if path already exists
        for entry in self._paths:
            if entry.path == normalized_path:
                logger.warning(f"Path already exists: {normalized_path}")
                # Update existing entry
                entry.description = description
                entry.enabled = enable
                return self._save_paths()
        
        # Add new path
        self._paths.append(PathEntry(
            path=normalized_path,
            enabled=enable,
            description=description
        ))
        
        logger.info(f"Added document path: {normalized_path} ({description})")
        return self._save_paths()
    
    def remove_path(self, path: str) -> bool:
        """
        Remove a document path.
        
        Args:
            path: The path to remove
            
        Returns:
            True if path was removed, False if path was not found
        """
        # Normalize path
        normalized_path = os.path.abspath(path) if os.path.isabs(path) else path
        
        # Find and remove the path
        for i, entry in enumerate(self._paths):
            if entry.path == normalized_path:
                removed_entry = self._paths.pop(i)
                logger.info(f"Removed document path: {removed_entry.path}")
                return self._save_paths()
        
        logger.warning(f"Path not found: {normalized_path}")
        return False
    
    def enable_path(self, path: str) -> bool:
        """
        Enable a document path.
        
        Args:
            path: The path to enable
            
        Returns:
            True if path was enabled, False if path was not found
        """
        normalized_path = os.path.abspath(path) if os.path.isabs(path) else path
        
        for entry in self._paths:
            if entry.path == normalized_path:
                if not entry.enabled:
                    entry.enabled = True
                    logger.info(f"Enabled document path: {normalized_path}")
                    return self._save_paths()
                else:
                    logger.info(f"Path already enabled: {normalized_path}")
                    return True
        
        logger.warning(f"Path not found: {normalized_path}")
        return False
    
    def disable_path(self, path: str) -> bool:
        """
        Disable a document path.
        
        Args:
            path: The path to disable
            
        Returns:
            True if path was disabled, False if path was not found
        """
        normalized_path = os.path.abspath(path) if os.path.isabs(path) else path
        
        for entry in self._paths:
            if entry.path == normalized_path:
                if entry.enabled:
                    entry.enabled = False
                    logger.info(f"Disabled document path: {normalized_path}")
                    return self._save_paths()
                else:
                    logger.info(f"Path already disabled: {normalized_path}")
                    return True
        
        logger.warning(f"Path not found: {normalized_path}")
        return False
    
    def list_paths(self, enabled_only: bool = False) -> List[PathEntry]:
        """
        List all document paths.
        
        Args:
            enabled_only: If True, only return enabled paths
            
        Returns:
            List of path entries
        """
        if enabled_only:
            return [entry for entry in self._paths if entry.enabled]
        return self._paths.copy()
    
    def get_enabled_paths(self) -> List[str]:
        """
        Get list of enabled paths as strings.
        
        Returns:
            List of enabled path strings
        """
        return [entry.path for entry in self._paths if entry.enabled]
    
    def path_exists(self, path: str) -> bool:
        """
        Check if a path exists in the manager.
        
        Args:
            path: The path to check
            
        Returns:
            True if path exists, False otherwise
        """
        normalized_path = os.path.abspath(path) if os.path.isabs(path) else path
        return any(entry.path == normalized_path for entry in self._paths)
    
    def is_path_enabled(self, path: str) -> bool:
        """
        Check if a path is enabled.
        
        Args:
            path: The path to check
            
        Returns:
            True if path exists and is enabled, False otherwise
        """
        normalized_path = os.path.abspath(path) if os.path.isabs(path) else path
        for entry in self._paths:
            if entry.path == normalized_path:
                return entry.enabled
        return False
    
    def clear_all_paths(self) -> bool:
        """Clear all document paths."""
        self._paths = []
        logger.info("Cleared all document paths")
        return self._save_paths()
    
    def reload(self) -> None:
        """Reload paths from settings file."""
        self._load_paths()


# Global instance for easy access
_path_manager: Optional[PathManager] = None


def get_path_manager() -> PathManager:
    """Get or create the global path manager instance."""
    global _path_manager
    if _path_manager is None:
        _path_manager = PathManager()
    return _path_manager


# Convenience functions using the global instance
def add_document_path(path: str, description: str = "", enable: bool = True) -> bool:
    """Add a document path (convenience function)."""
    return get_path_manager().add_path(path, description, enable)


def remove_document_path(path: str) -> bool:
    """Remove a document path (convenience function)."""
    return get_path_manager().remove_path(path)


def enable_document_path(path: str) -> bool:
    """Enable a document path (convenience function)."""
    return get_path_manager().enable_path(path)


def disable_document_path(path: str) -> bool:
    """Disable a document path (convenience function)."""
    return get_path_manager().disable_path(path)


def list_document_paths(enabled_only: bool = False) -> List[PathEntry]:
    """List document paths (convenience function)."""
    return get_path_manager().list_paths(enabled_only)


def get_enabled_document_paths() -> List[str]:
    """Get enabled document paths (convenience function)."""
    return get_path_manager().get_enabled_paths()


def clear_all_document_paths() -> bool:
    """Clear all document paths (convenience function)."""
    return get_path_manager().clear_all_paths()


def reload_document_paths() -> None:
    """Reload document paths from settings file (convenience function)."""
    get_path_manager().reload()


# Integration with existing ingestion system
def update_ingestion_paths() -> List[str]:
    """
    Update the global settings with current enabled paths.
    
    This function should be called after modifying paths to ensure
    the ingestion system uses the updated paths.
    
    Returns:
        List of enabled paths
    """
    enabled_paths = get_enabled_document_paths()
    
    # Update the global settings object
    try:
        import src.settings as settings_module
        
        # Check if settings has DOCS_PATHS attribute
        if hasattr(settings_module, 'DOCS_PATHS'):
            settings_module.DOCS_PATHS = enabled_paths
            logger.info(f"Updated settings.DOCS_PATHS with {len(enabled_paths)} paths")
        else:
            logger.warning("settings module does not have DOCS_PATHS attribute")
            
    except ImportError:
        logger.warning("Could not import settings module")
    
    return enabled_paths
