"""Domain exception hierarchy for the RAG pipeline.

All domain errors inherit from RagError, which carries the original cause.
Use these exceptions as the error value in Result.err(...).

Layer mapping:
  IngestionError   → src/workflows/ingestion/
  StorageError     → src/backends/storage/
  QueryError       → src/workflows/query/
  MemoryError      → src/workflows/memory/
  ConfigError      → src/conf / startup
"""

from typing import Optional


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class RagError(Exception):
    """Base class for all domain errors in the RAG pipeline."""

    def __init__(self, message: str, cause: Optional[Exception] = None) -> None:
        super().__init__(message)
        self.cause = cause

    def __str__(self) -> str:
        base = super().__str__()
        if self.cause:
            return f"{base} (caused by {type(self.cause).__name__}: {self.cause})"
        return base


# ---------------------------------------------------------------------------
# Ingestion layer
# ---------------------------------------------------------------------------

class IngestionError(RagError):
    """Base class for ingestion pipeline errors."""


class ScanError(IngestionError):
    """Raised when the file-system scanner fails to traverse a path."""

    def __init__(self, path: str, cause: Optional[Exception] = None) -> None:
        super().__init__(f"Scan failed for path: {path}", cause)
        self.path = path


class LoaderError(IngestionError):
    """Raised when a document loader cannot read or parse a file."""


class LoaderFileNotFoundError(LoaderError):
    """Raised when a loader cannot find the file to process."""

    def __init__(self, path: str) -> None:
        super().__init__(f"File not found: {path}")
        self.path = path


class LoaderDependencyError(LoaderError):
    """Raised when a loader requires an optional dependency that is missing."""

    def __init__(self, dependency: str, detail: Optional[str] = None) -> None:
        message = f"Required dependency missing: {dependency}"
        if detail:
            message = f"{message}. {detail}"
        super().__init__(message)
        self.dependency = dependency


class LoaderInvalidFormatError(LoaderError):
    """Raised when a file does not match the expected format."""

    def __init__(self, path: str, expected: str, detail: Optional[str] = None) -> None:
        message = f"Invalid format for {path}. Expected: {expected}"
        if detail:
            message = f"{message}. {detail}"
        super().__init__(message)
        self.path = path
        self.expected = expected


class LoaderUnreadableTextError(LoaderError):
    """Raised when a text-like file cannot be decoded or appears to be binary."""

    def __init__(self, path: str, detail: str) -> None:
        super().__init__(f"Unreadable text encoding for {path}: {detail}")
        self.path = path
        self.detail = detail


class ChunkError(IngestionError):
    """Raised when document splitting or chunking fails."""

    def __init__(self, path: str, cause: Optional[Exception] = None) -> None:
        super().__init__(f"Chunking failed for: {path}", cause)
        self.path = path


class EmbeddingError(IngestionError):
    """Raised when embedding generation fails for a chunk or batch."""

    def __init__(self, detail: str, cause: Optional[Exception] = None) -> None:
        super().__init__(f"Embedding failed: {detail}", cause)


class LedgerError(IngestionError):
    """Raised when the ingestion ledger (SQLite) cannot be read or written."""

    def __init__(self, detail: str, cause: Optional[Exception] = None) -> None:
        super().__init__(f"Ledger operation failed: {detail}", cause)


class ScoreCacheError(IngestionError):
    """Raised when the score cache cannot be read or written."""

    def __init__(self, detail: str, cause: Optional[Exception] = None) -> None:
        super().__init__(f"Score cache operation failed: {detail}", cause)


# ---------------------------------------------------------------------------
# Storage layer
# ---------------------------------------------------------------------------

class StorageError(RagError):
    """Base class for storage backend errors."""


class VectorStoreError(StorageError):
    """Raised when a Weaviate (vector store) operation fails."""

    def __init__(self, operation: str, detail: str, cause: Optional[Exception] = None) -> None:
        super().__init__(f"Vector store error during {operation}: {detail}", cause)
        self.operation = operation


class VectorDimensionMismatchError(VectorStoreError):
    """Raised when the embedding dimension does not match the collection schema."""

    def __init__(self, new_dim: int, existing_dim: int) -> None:
        super().__init__(
            operation="upsert",
            detail=f"dimension mismatch: got {new_dim}, collection expects {existing_dim}",
        )
        self.new_dim = new_dim
        self.existing_dim = existing_dim


class GraphError(StorageError):
    """Raised when a Neo4j (graph store) operation fails."""

    def __init__(self, operation: str, detail: str, cause: Optional[Exception] = None) -> None:
        super().__init__(f"Graph store error during {operation}: {detail}", cause)
        self.operation = operation


class CacheError(StorageError):
    """Raised when a cache (Redis, SQLite, xattr) operation fails."""

    def __init__(self, detail: str, cause: Optional[Exception] = None) -> None:
        super().__init__(f"Cache operation failed: {detail}", cause)


# ---------------------------------------------------------------------------
# Query layer
# ---------------------------------------------------------------------------

class QueryError(RagError):
    """Base class for query pipeline errors."""


class RetrievalError(QueryError):
    """Raised when vector or keyword retrieval fails."""


class RetrievalTimeoutError(RetrievalError):
    """Raised when retrieval exceeds the configured timeout."""


class RetrievalConnectionError(RetrievalError):
    """Raised when the connection to the retrieval backend fails."""


class GenerationError(QueryError):
    """Raised when the LLM generation step fails."""

    def __init__(self, detail: str, cause: Optional[Exception] = None) -> None:
        super().__init__(f"Generation failed: {detail}", cause)


# ---------------------------------------------------------------------------
# Memory layer
# ---------------------------------------------------------------------------

class MemoryError(RagError):  # noqa: A001  (shadows built-in intentionally within this domain)
    """Base class for conversation memory errors."""


class SnapshotError(MemoryError):
    """Raised when creating or persisting a conversation snapshot fails."""

    def __init__(self, detail: str, cause: Optional[Exception] = None) -> None:
        super().__init__(f"Snapshot error: {detail}", cause)


class ChatPersistenceError(MemoryError):
    """Raised when reading or writing chat history to the store fails."""

    def __init__(self, detail: str, cause: Optional[Exception] = None) -> None:
        super().__init__(f"Chat persistence error: {detail}", cause)


# ---------------------------------------------------------------------------
# Configuration / startup
# ---------------------------------------------------------------------------

class ConfigError(RagError):
    """Raised when a required configuration value is missing or invalid."""

    def __init__(self, setting: str, detail: str) -> None:
        super().__init__(f"Configuration error for '{setting}': {detail}")
        self.setting = setting


__all__ = [
    # Base
    "RagError",
    # Ingestion
    "IngestionError",
    "ScanError",
    "LoaderError",
    "LoaderFileNotFoundError",
    "LoaderDependencyError",
    "LoaderInvalidFormatError",
    "LoaderUnreadableTextError",
    "ChunkError",
    "EmbeddingError",
    "LedgerError",
    "ScoreCacheError",
    # Storage
    "StorageError",
    "VectorStoreError",
    "VectorDimensionMismatchError",
    "GraphError",
    "CacheError",
    # Query
    "QueryError",
    "RetrievalError",
    "RetrievalTimeoutError",
    "RetrievalConnectionError",
    "GenerationError",
    # Memory
    "MemoryError",
    "SnapshotError",
    "ChatPersistenceError",
    # Config
    "ConfigError",
]
