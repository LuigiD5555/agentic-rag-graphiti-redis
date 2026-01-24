"""SQLite control plane for RAG system.

This module provides SQLite-based storage for:
- Scan checkpointing and resumibility
- File metadata and phase status tracking
- Chunk registry and idempotence
- Session preferences (privacy switch)
- Audit events
"""

import sqlite3
import time
from pathlib import Path
from typing import Optional
from dataclasses import dataclass
from enum import Enum

from src import logger


class ScanRunStatus(Enum):
    """Status of a scan run."""
    NEW = "NEW"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class FileStatus(Enum):
    """Status of file processing."""
    NEW = "NEW"
    EXTRACTED = "EXTRACTED"
    CHUNKED = "CHUNKED"
    EMBEDDED = "EMBEDDED"
    UPSERTED = "UPSERTED"
    FAILED = "FAILED"


class ChunkStatus(Enum):
    """Status of chunk processing."""
    NEW = "NEW"
    EMBEDDED = "EMBEDDED"
    UPSERTED = "UPSERTED"
    FAILED = "FAILED"


@dataclass
class ScanRun:
    """Represents a scan run."""
    run_id: str
    root_paths_json: str
    options_hash: str
    status: ScanRunStatus
    started_at: int
    updated_at: int
    dirs_visited: int = 0
    files_found: int = 0
    last_error: Optional[str] = None


@dataclass
class FileMetadata:
    """Represents file metadata and processing status."""
    file_path: str
    mtime_ns: int
    size_bytes: int
    content_hash: Optional[str]
    fingerprint_hash: str
    status: FileStatus
    run_id_last: Optional[str]
    updated_at: int
    last_error: Optional[str] = None


@dataclass
class ChunkMetadata:
    """Represents chunk metadata and processing status."""
    chunk_id: str
    file_path: str
    chunk_index: int
    chunk_hash: str
    status: ChunkStatus
    vector_id: Optional[str] = None
    retry_count: int = 0
    updated_at: int = 0
    last_error: Optional[str] = None


@dataclass
class UserSession:
    """Represents user session preferences."""
    session_id: str
    created_at: int
    updated_at: int
    llm_pii_allowed: bool = False
    llm_trust_label: str = "untrusted"
    preferred_answer_style: Optional[str] = None
    notes: Optional[str] = None


@dataclass
class AuditEvent:
    """Represents an audit event."""
    event_id: str
    session_id: str
    event_type: str
    event_at: int
    metadata_json: str


class SQLiteControlPlane:
    """SQLite control plane for RAG system."""
    
    def __init__(self, db_path: str):
        """
        Initialize SQLite control plane.
        
        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = db_path
        self.is_memory_db = db_path == ":memory:" or ":memory:" in db_path
        
        if not self.is_memory_db:
            path_obj = Path(db_path)
            path_obj.parent.mkdir(parents=True, exist_ok=True)
        
        # For in-memory databases, we need to keep a persistent connection
        # to prevent the database from being destroyed
        self._persistent_conn = None
        
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema."""
        if self.is_memory_db:
            # For in-memory databases, create and keep a persistent connection
            self._persistent_conn = self._get_connection_for_init()
            conn = self._persistent_conn
        else:
            # For file-based databases, create a temporary connection
            conn = self._get_connection_for_init()
        
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA foreign_keys=ON")
            
            # Create schema versioning table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at INTEGER NOT NULL
                )
            """)
            
            # Apply migrations
            self._apply_migrations(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            if not self.is_memory_db:
                # Only close file-based connections
                conn.close()
    
    def __del__(self):
        """Clean up persistent connection if it exists."""
        if self._persistent_conn:
            self._persistent_conn.close()
    
    def _get_connection_for_init(self) -> sqlite3.Connection:
        """Get connection for initialization."""
        if self.is_memory_db:
            # For in-memory databases, use shared cache with a named database
            # This ensures all connections share the same in-memory database
            return sqlite3.connect("file:rag_control_plane?mode=memory&cache=shared", uri=True)
        else:
            return sqlite3.connect(self.db_path)
    
    def _apply_migrations(self, conn: sqlite3.Connection):
        """Apply database migrations."""
        current_version = self._get_current_version(conn)
        
        migrations = [
            (1, self._migration_001_initial_schema),
            (2, self._migration_002_add_session_audit),
            (3, self._migration_003_add_chunk_registry),
        ]
        
        for version, migration_func in migrations:
            if version > current_version:
                logger.info(f"Applying migration {version}")
                migration_func(conn)
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                    (version, int(time.time()))
                )
    
    def _get_current_version(self, conn: sqlite3.Connection) -> int:
        """Get current schema version."""
        try:
            result = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
            return result[0] if result[0] is not None else 0
        except sqlite3.OperationalError:
            return 0
    
    def _migration_001_initial_schema(self, conn: sqlite3.Connection):
        """Initial schema migration."""
        # Scan runs
        conn.execute("""
            CREATE TABLE scan_runs (
                run_id TEXT PRIMARY KEY,
                root_paths_json TEXT NOT NULL,
                options_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                dirs_visited INTEGER DEFAULT 0,
                files_found INTEGER DEFAULT 0,
                last_error TEXT
            )
        """)
        
        # Scan pending directories
        conn.execute("""
            CREATE TABLE scan_pending (
                run_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                dir_path TEXT NOT NULL,
                enqueued_at INTEGER NOT NULL,
                UNIQUE(run_id, dir_path),
                FOREIGN KEY(run_id) REFERENCES scan_runs(run_id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX idx_scan_pending_run_seq ON scan_pending(run_id, seq)")
        
        # Scan visited directories
        conn.execute("""
            CREATE TABLE scan_visited (
                run_id TEXT NOT NULL,
                dir_path TEXT NOT NULL,
                visited_at INTEGER NOT NULL,
                UNIQUE(run_id, dir_path),
                FOREIGN KEY(run_id) REFERENCES scan_runs(run_id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX idx_scan_visited_run_dir ON scan_visited(run_id, dir_path)")
        
        # Scan discovered files
        conn.execute("""
            CREATE TABLE scan_files (
                run_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                file_path TEXT NOT NULL,
                found_at INTEGER NOT NULL,
                UNIQUE(run_id, file_path),
                FOREIGN KEY(run_id) REFERENCES scan_runs(run_id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX idx_scan_files_run_seq ON scan_files(run_id, seq)")
        
        # File metadata
        conn.execute("""
            CREATE TABLE files (
                file_path TEXT PRIMARY KEY,
                mtime_ns INTEGER NOT NULL,
                size_bytes INTEGER NOT NULL,
                content_hash TEXT,
                fingerprint_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                run_id_last TEXT,
                updated_at INTEGER NOT NULL,
                last_error TEXT
            )
        """)
        conn.execute("CREATE INDEX idx_files_status ON files(status)")
        conn.execute("CREATE INDEX idx_files_fingerprint ON files(fingerprint_hash)")
        conn.execute("CREATE INDEX idx_files_content_hash ON files(content_hash)")
    
    def _migration_002_add_session_audit(self, conn: sqlite3.Connection):
        """Add session and audit tables."""
        # User sessions
        conn.execute("""
            CREATE TABLE user_sessions (
                session_id TEXT PRIMARY KEY,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                llm_pii_allowed INTEGER NOT NULL DEFAULT 0,
                llm_trust_label TEXT NOT NULL DEFAULT 'untrusted',
                preferred_answer_style TEXT,
                notes TEXT
            )
        """)
        
        # Audit events
        conn.execute("""
            CREATE TABLE audit_events (
                event_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                event_at INTEGER NOT NULL,
                metadata_json TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES user_sessions(session_id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX idx_audit_events_session ON audit_events(session_id)")
        conn.execute("CREATE INDEX idx_audit_events_type ON audit_events(event_type)")
    
    def _migration_003_add_chunk_registry(self, conn: sqlite3.Connection):
        """Add chunk registry and ingestion runs tables."""
        # Chunk registry
        conn.execute("""
            CREATE TABLE chunks (
                chunk_id TEXT PRIMARY KEY,
                file_path TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                chunk_hash TEXT NOT NULL,
                status TEXT NOT NULL,
                vector_id TEXT,
                retry_count INTEGER DEFAULT 0,
                updated_at INTEGER NOT NULL,
                last_error TEXT,
                UNIQUE(file_path, chunk_index, chunk_hash),
                FOREIGN KEY(file_path) REFERENCES files(file_path) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX idx_chunks_file_path ON chunks(file_path)")
        conn.execute("CREATE INDEX idx_chunks_status ON chunks(status)")
        
        # Ingestion runs (optional)
        conn.execute("""
            CREATE TABLE ingest_runs (
                run_id TEXT PRIMARY KEY,
                started_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL,
                status TEXT NOT NULL,
                options_hash TEXT NOT NULL,
                last_error TEXT
            )
        """)
    
    def get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        if self.is_memory_db:
            # For in-memory databases, use shared cache with the same named database
            conn = sqlite3.connect("file:rag_control_plane?mode=memory&cache=shared", uri=True)
        else:
            conn = sqlite3.connect(self.db_path)
        
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn
