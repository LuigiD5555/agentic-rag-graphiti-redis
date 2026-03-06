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
    DELETED = "DELETED"


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
    scan_run_id: Optional[str] = None
    ingestion_run_id: Optional[str] = None
    chunk_ids_json: Optional[str] = None


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
            return sqlite3.connect(
                "file:rag_control_plane?mode=memory&cache=shared",
                uri=True,
                isolation_level=None  # Enable autocommit mode
            )
        else:
            return sqlite3.connect(self.db_path)
    
    def _apply_migrations(self, conn: sqlite3.Connection):
        """Apply database migrations."""
        current_version = self._get_current_version(conn)
        
        migrations = [
            (1, self._migration_001_initial_schema),
            (2, self._migration_002_add_session_audit),
            (3, self._migration_003_add_chunk_registry),
            (4, self._migration_004_add_temporal_tracking),
            (5, self._migration_005_add_memory_checkpoints),
            (6, self._migration_006_add_ingest_queue_and_file_tracking),
            (7, self._migration_007_add_cache_tables),
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

    def _migration_004_add_temporal_tracking(self, conn: sqlite3.Connection):
        """Add temporal file tracking tables."""
        conn.execute("""
            CREATE TABLE temporal_files (
                thread_id TEXT NOT NULL,
                file_id TEXT NOT NULL,
                file_hash TEXT NOT NULL,
                filename TEXT NOT NULL,
                uploaded_at INTEGER NOT NULL,
                query_count INTEGER NOT NULL DEFAULT 0,
                pareto_promoted INTEGER NOT NULL DEFAULT 0,
                full_promoted INTEGER NOT NULL DEFAULT 0,
                chunk_ids_json TEXT NOT NULL,
                expires_at INTEGER NOT NULL,
                PRIMARY KEY (thread_id, file_id)
            )
        """)
        conn.execute("CREATE INDEX idx_temporal_files_thread ON temporal_files(thread_id)")
        conn.execute("CREATE INDEX idx_temporal_files_expires ON temporal_files(expires_at)")

        conn.execute("""
            CREATE TABLE file_uploads (
                file_hash TEXT PRIMARY KEY,
                upload_count INTEGER NOT NULL,
                first_uploaded INTEGER NOT NULL,
                last_uploaded INTEGER NOT NULL,
                filename TEXT NOT NULL,
                promoted INTEGER NOT NULL DEFAULT 0,
                pareto_promoted INTEGER NOT NULL DEFAULT 0
            )
        """)

        conn.execute("""
            CREATE TABLE file_upload_threads (
                file_hash TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                PRIMARY KEY (file_hash, thread_id),
                FOREIGN KEY(file_hash) REFERENCES file_uploads(file_hash) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX idx_file_upload_threads_thread ON file_upload_threads(thread_id)")

        conn.execute("""
            CREATE TABLE chunk_scores (
                thread_id TEXT NOT NULL,
                file_id TEXT NOT NULL,
                chunk_id TEXT NOT NULL,
                score REAL NOT NULL,
                PRIMARY KEY (thread_id, file_id, chunk_id),
                FOREIGN KEY(thread_id, file_id) REFERENCES temporal_files(thread_id, file_id) ON DELETE CASCADE
            )
        """)
        conn.execute("CREATE INDEX idx_chunk_scores_file ON chunk_scores(thread_id, file_id)")

        conn.execute("""
            CREATE TABLE temporal_tenants (
                tenant_name TEXT PRIMARY KEY,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            )
        """)
        conn.execute("CREATE INDEX idx_temporal_tenants_expires ON temporal_tenants(expires_at)")

    def _migration_005_add_memory_checkpoints(self, conn: sqlite3.Connection):
        """Add memory checkpoint storage."""
        conn.execute("""
            CREATE TABLE memory_checkpoints (
                thread_id TEXT NOT NULL,
                checkpoint_ns TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                metadata_json TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                updated_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                PRIMARY KEY (thread_id, checkpoint_ns)
            )
        """)
        conn.execute("CREATE INDEX idx_memory_checkpoints_expires ON memory_checkpoints(expires_at)")

    def _migration_006_add_ingest_queue_and_file_tracking(self, conn: sqlite3.Connection):
        """Add ingestion queue tables and file tracking metadata."""
        # Extend files table for run tracking and chunk linkage
        conn.execute("ALTER TABLE files ADD COLUMN scan_run_id TEXT")
        conn.execute("ALTER TABLE files ADD COLUMN ingestion_run_id TEXT")
        conn.execute("ALTER TABLE files ADD COLUMN chunk_ids_json TEXT")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_files_scan_run_id ON files(scan_run_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_files_ingestion_run_id ON files(ingestion_run_id)")

        # File run tracking (for deletion detection and history)
        conn.execute("""
            CREATE TABLE ingest_file_runs (
                run_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                seen_at INTEGER NOT NULL,
                PRIMARY KEY (run_id, file_path)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ingest_file_runs_run ON ingest_file_runs(run_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ingest_file_runs_file ON ingest_file_runs(file_path)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ingest_file_runs_seen ON ingest_file_runs(seen_at)")

        # Chunk file metadata (optional, for registry summaries)
        conn.execute("""
            CREATE TABLE chunk_files (
                file_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                total_chunks INTEGER NOT NULL,
                run_id TEXT,
                chunking_params_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                status TEXT NOT NULL,
                PRIMARY KEY (file_id, file_path)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chunk_files_file_path ON chunk_files(file_path)")

        # Ingestion queue
        conn.execute("""
            CREATE TABLE ingest_jobs (
                job_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                scan_run_id TEXT,
                file_path TEXT NOT NULL,
                options_json TEXT,
                priority INTEGER NOT NULL DEFAULT 0,
                retry_count INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                enqueued_at INTEGER NOT NULL,
                started_at INTEGER,
                completed_at INTEGER,
                error TEXT,
                consumer_name TEXT,
                updated_at INTEGER NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ingest_jobs_status ON ingest_jobs(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ingest_jobs_enqueued ON ingest_jobs(enqueued_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ingest_jobs_consumer ON ingest_jobs(consumer_name)")

        conn.execute("""
            CREATE TABLE ingest_consumers (
                consumer_name TEXT PRIMARY KEY,
                last_seen INTEGER NOT NULL,
                consumer_group TEXT
            )
        """)

    def _migration_007_add_cache_tables(self, conn: sqlite3.Connection):
        """Add SQLite-backed cache tables (ingestion + kv + embeddings)."""
        conn.execute("""
            CREATE TABLE ingestion_file_cache (
                file_path TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL,
                mtime REAL NOT NULL,
                size_bytes INTEGER NOT NULL,
                last_processed REAL NOT NULL,
                chunk_count INTEGER NOT NULL,
                embedding_count INTEGER NOT NULL,
                status TEXT NOT NULL,
                error_message TEXT,
                ingestion_run_id TEXT,
                scan_run_id TEXT,
                chunk_ids TEXT,
                expires_at INTEGER NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ingestion_file_cache_hash ON ingestion_file_cache(content_hash)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ingestion_file_cache_expires ON ingestion_file_cache(expires_at)")

        conn.execute("""
            CREATE TABLE ingestion_dir_cache (
                dir_path TEXT PRIMARY KEY,
                structure_hash TEXT NOT NULL,
                file_count INTEGER NOT NULL,
                last_scanned REAL NOT NULL,
                total_size INTEGER NOT NULL,
                expires_at INTEGER NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ingestion_dir_cache_expires ON ingestion_dir_cache(expires_at)")

        conn.execute("""
            CREATE TABLE ingestion_hash_index (
                content_hash TEXT NOT NULL,
                file_path TEXT NOT NULL,
                PRIMARY KEY (content_hash, file_path)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ingestion_hash_index_hash ON ingestion_hash_index(content_hash)")

        conn.execute("""
            CREATE TABLE cache_kv (
                cache_key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                expires_at INTEGER NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_kv_expires ON cache_kv(expires_at)")

        conn.execute("""
            CREATE TABLE embedding_cache (
                cache_key TEXT PRIMARY KEY,
                embedding_json TEXT NOT NULL,
                expires_at INTEGER NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_embedding_cache_expires ON embedding_cache(expires_at)")
    
    def get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        if self.is_memory_db:
            # For in-memory databases, use shared cache with the same named database
            conn = sqlite3.connect(
                "file:rag_control_plane?mode=memory&cache=shared",
                uri=True,
                timeout=30,
            )
        else:
            conn = sqlite3.connect(self.db_path, timeout=30)

        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn
