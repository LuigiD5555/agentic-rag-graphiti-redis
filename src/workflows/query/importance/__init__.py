"""Document importance classification for dual embedding system."""

from src.workflows.query.importance.classifier import (
    DocumentImportanceClassifier,
    ImportanceLevel,
)

__all__ = ["DocumentImportanceClassifier", "ImportanceLevel"]
