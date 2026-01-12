"""Document importance classifier for dual embedding system.

Determines which documents should use high-dimensional embeddings (768)
vs low-dimensional embeddings (384) based on various heuristics.
"""

import os
from pathlib import Path
from typing import List, Set, Optional
from enum import Enum


class ImportanceLevel(Enum):
    """Importance levels for documents."""
    HIGH = "high"  # Use 768-dim embeddings
    LOW = "low"    # Use 384-dim embeddings


class DocumentImportanceClassifier:
    """Classifies documents by importance to determine embedding dimension."""

    # File extensions considered high-importance (technical/structured content)
    HIGH_IMPORTANCE_EXTENSIONS: Set[str] = {
        ".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".cpp", ".c", ".h", ".hpp",
        ".go", ".rs", ".rb", ".php", ".cs", ".swift", ".kt", ".scala",
        ".sql", ".json", ".yaml", ".yml", ".toml", ".xml",
        ".md", ".rst", ".tex",  # Technical documentation
        ".ipynb",  # Jupyter notebooks
        ".sh", ".bash", ".zsh", ".fish",  # Scripts
    }

    # File extensions considered low-importance (general content)
    LOW_IMPORTANCE_EXTENSIONS: Set[str] = {
        ".txt", ".log", ".csv",
        ".html", ".css",  # Web content (usually less critical)
    }

    # Path patterns that indicate high importance
    HIGH_IMPORTANCE_PATTERNS: Set[str] = {
        "src/", "lib/", "core/", "api/", "backend/", "frontend/",
        "docs/technical/", "specs/", "design/",
        "tests/", "test/",  # Test code is important
        "config/", "conf/",
    }

    # Path patterns that indicate low importance
    LOW_IMPORTANCE_PATTERNS: Set[str] = {
        "tmp/", "temp/", "cache/", "backup/", "old/", "archive/",
        "node_modules/", "vendor/", ".git/", "__pycache__/",
        "logs/", "log/",
    }

    # Filename patterns that indicate high importance
    HIGH_IMPORTANCE_FILENAMES: Set[str] = {
        "readme.md", "readme", "contributing.md", "license", "changelog.md",
        "makefile", "dockerfile", "docker-compose.yml", "requirements.txt",
        "package.json", "setup.py", "pyproject.toml", "cargo.toml",
    }

    def __init__(
        self,
        custom_high_importance_extensions: Optional[Set[str]] = None,
        custom_high_importance_patterns: Optional[Set[str]] = None,
    ):
        """Initialize classifier with optional custom rules.

        Args:
            custom_high_importance_extensions: Additional file extensions to treat as high importance
            custom_high_importance_patterns: Additional path patterns to treat as high importance
        """
        self.high_importance_extensions = (
            self.HIGH_IMPORTANCE_EXTENSIONS.copy()
        )
        self.low_importance_extensions = (
            self.LOW_IMPORTANCE_EXTENSIONS.copy()
        )
        self.high_importance_patterns = (
            self.HIGH_IMPORTANCE_PATTERNS.copy()
        )
        self.low_importance_patterns = (
            self.LOW_IMPORTANCE_PATTERNS.copy()
        )

        if custom_high_importance_extensions:
            self.high_importance_extensions.update(custom_high_importance_extensions)

        if custom_high_importance_patterns:
            self.high_importance_patterns.update(custom_high_importance_patterns)

    def classify(self, file_path: str) -> ImportanceLevel:
        """Classify a document's importance level.

        Args:
            file_path: Path to the document

        Returns:
            ImportanceLevel enum indicating HIGH or LOW importance
        """
        path = Path(file_path)
        extension = path.suffix.lower()
        filename = path.name.lower()
        path_str = str(path).lower()

        # Rule 1: Check filename patterns (highest priority)
        if filename in self.HIGH_IMPORTANCE_FILENAMES:
            return ImportanceLevel.HIGH

        # Rule 2: Check for low-importance path patterns (exclusions)
        for pattern in self.low_importance_patterns:
            if pattern in path_str:
                return ImportanceLevel.LOW

        # Rule 3: Check for high-importance path patterns
        for pattern in self.high_importance_patterns:
            if pattern in path_str:
                return ImportanceLevel.HIGH

        # Rule 4: Check file extension
        if extension in self.high_importance_extensions:
            return ImportanceLevel.HIGH

        if extension in self.low_importance_extensions:
            return ImportanceLevel.LOW

        # Rule 5: File size heuristic (smaller files often more important)
        # This is a soft heuristic - can be disabled if not desired
        try:
            if os.path.exists(file_path):
                size_kb = os.path.getsize(file_path) / 1024
                # Files < 100KB tend to be configs, code, docs (important)
                # Files > 1MB tend to be data dumps, logs (less important)
                if size_kb < 100:
                    return ImportanceLevel.HIGH
                elif size_kb > 1024:
                    return ImportanceLevel.LOW
        except (OSError, FileNotFoundError):
            pass  # If we can't check size, continue with other rules

        # Default: treat as high importance (conservative approach)
        # Better to use more memory than lose quality on important docs
        return ImportanceLevel.HIGH

    def classify_batch(self, file_paths: List[str]) -> List[ImportanceLevel]:
        """Classify multiple documents at once.

        Args:
            file_paths: List of file paths to classify

        Returns:
            List of ImportanceLevel enums matching the input order
        """
        return [self.classify(path) for path in file_paths]

    def get_statistics(self, file_paths: List[str]) -> dict:
        """Get classification statistics for a batch of files.

        Args:
            file_paths: List of file paths to analyze

        Returns:
            Dictionary with classification statistics
        """
        classifications = self.classify_batch(file_paths)
        high_count = sum(1 for c in classifications if c == ImportanceLevel.HIGH)
        low_count = sum(1 for c in classifications if c == ImportanceLevel.LOW)

        return {
            "total_files": len(file_paths),
            "high_importance": high_count,
            "low_importance": low_count,
            "high_percentage": (high_count / len(file_paths) * 100) if file_paths else 0,
            "low_percentage": (low_count / len(file_paths) * 100) if file_paths else 0,
        }


__all__ = ["DocumentImportanceClassifier", "ImportanceLevel"]
