"""Ledger repository for SQLite control plane operations.

- get_or_create_document
- ensure_version
- claim_stage
- mark_stage_done/failed
- register_artifact
- list_expired_artifacts
"""

import os
import time
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass
from enum import Enum

from src.backends.storage.sqlite.manager import get_sqlite_manager
from src.workflows.query.audit import get_logger

log = get_logger(__name__)


class Stage(Enum):
    """Processing stages."""
    DISCOVER = "DISCOVER"
    EXTRACT = "EXTRACT"
    CHUNK = "CHUNK"
    EMBED = "EMBED"
    UPSERT = "UPSERT"
    FINALIZE = "FINALIZE"
    JANITOR = "JANITOR"


class VersionDecision(Enum):
    """Version decision types."""
    SKIP = "SKIP"
    NEW_ACTIVE = "NEW_ACTIVE"
    ALREADY_ACTIVE = "ALREADY_ACTIVE"


class ClaimResult(Enum):
    """Claim result types."""
    DONE = "DONE"
    CLAIMED = "CLAIMED"
    IN_PROGRESS_RECENT = "IN_PROGRESS_RECENT"
    RECLAIMED_STALE = "RECLAIMED_STALE"


@dataclass
class VersionDecisionResult:
    """Result of ensure_version operation."""
    decision: VersionDecision
    new_version_id: Optional[str] = None
    superseded_version_id: Optional[str] = None


@dataclass
class ClaimResultData:
    """Result of claim_stage operation."""
    should_process: bool
    reason: ClaimResult


@dataclass
class Artifact:
    """Artifact metadata."""
    version_id: str
    artifact_kind: str
    artifact_ref: str
    expires_at: Optional[int] = None


class LedgerRepository:
    """SQLite ledger repository implementing plan V2 algorithms."""
    
    def __init__(self):
        self.sqlite_manager = get_sqlite_manager()
        self.control_plane = self.sqlite_manager.control_plane
        self._ensure_tables()
    
    def _ensure_tables(self) -> None:
        """Ensure required tables exist in SQLite."""
        with self.control_plane.get_connection() as conn:
            # Documents table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL UNIQUE,
                    active_version_id TEXT,
                    last_seen_fingerprint TEXT,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
            """)
            
            # Document versions table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS document_versions (
                    version_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    archived_at INTEGER,
                    superseded_by_version_id TEXT,
                    FOREIGN KEY(document_id) REFERENCES documents(document_id)
                )
            """)
            
            # Version stage states table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS version_stage_state (
                    version_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    owner TEXT,
                    attempt INTEGER DEFAULT 0,
                    updated_at INTEGER NOT NULL,
                    error_last TEXT,
                    PRIMARY KEY (version_id, stage),
                    FOREIGN KEY(version_id) REFERENCES document_versions(version_id)
                )
            """)
            
            # Artifacts table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    version_id TEXT NOT NULL,
                    artifact_kind TEXT NOT NULL,
                    artifact_ref TEXT NOT NULL,
                    created_at INTEGER NOT NULL,
                    expires_at INTEGER,
                    FOREIGN KEY(version_id) REFERENCES document_versions(version_id)
                )
            """)
            
            # Create indexes
            conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_file_path ON documents(file_path)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_document_versions_document_id "
                "ON document_versions(document_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_document_versions_status "
                "ON document_versions(status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_version_stage_state_status "
                "ON version_stage_state(status)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_artifacts_expires "
                "ON artifacts(expires_at)"
            )

            # Content deduplication table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS content_fingerprints (
                    fingerprint TEXT NOT NULL,
                    canonical_document_id TEXT NOT NULL,
                    PRIMARY KEY (fingerprint),
                    FOREIGN KEY(canonical_document_id) REFERENCES documents(document_id)
                )
            """)
    
    def _normalize_path(self, file_path: str) -> str:
        """Normalize file path."""
        path = Path(file_path)
        try:
            # Resolve symlinks if they exist
            resolved = path.resolve()
            return str(resolved)
        except Exception:
            # If resolution fails, return absolute path
            return str(path.absolute())
    
    def get_or_create_document(self, file_path: str) -> str:
        """Get or create document ID for a file path.
        
        Algorithm from plan 3.1.1:
        1) Normalize path
        2) Search in documents by file_path
        3) If exists → return document_id
        4) If not exists:
           - document_id = sha256(file_path_normalized)
           - Insert row with active_version_id=NULL and last_seen_fingerprint=NULL
           - return document_id
        """
        normalized_path = self._normalize_path(file_path)
        
        with self.control_plane.get_connection() as conn:
            # Check if document exists
            cursor = conn.execute(
                "SELECT document_id FROM documents WHERE file_path = ?",
                (normalized_path,)
            )
            row = cursor.fetchone()
            
            if row:
                return row[0]
            
            # Create new document
            document_id = hashlib.sha256(normalized_path.encode()).hexdigest()
            now_ts = int(time.time())
            
            conn.execute("""
                INSERT INTO documents (document_id, file_path, active_version_id, 
                                     last_seen_fingerprint, created_at, updated_at)
                VALUES (?, ?, NULL, NULL, ?, ?)
            """, (document_id, normalized_path, now_ts, now_ts))
            
            return document_id
    
    def get_active_version(self, document_id: str) -> Optional[str]:
        """Get active version ID for a document."""
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute(
                "SELECT active_version_id FROM documents WHERE document_id = ?",
                (document_id,)
            )
            row = cursor.fetchone()
            return row[0] if row else None
    
    def ensure_version(self, document_id: str, fingerprint: str) -> VersionDecisionResult:
        """Ensure version exists and return decision.
        
        Algorithm from plan 3.1.3:
        1) new_version_id = fingerprint
        2) Read document: active_version_id, last_seen_fingerprint
        3) If last_seen_fingerprint == fingerprint and active_version_id == new_version_id:
           - return ALREADY_ACTIVE (no publish)
        4) If document has no previous version:
           - Insert new version with status=ACTIVE
           - Update documents.active_version_id=new_version_id, last_seen_fingerprint=fingerprint
           - return NEW_ACTIVE, superseded=None
        5) If previous version different:
           - old = active_version_id
           - Insert new version status=ACTIVE
           - Update old version status=SUPERSEDED, superseded_by_version_id=new
           - Update documents.active_version_id=new, last_seen_fingerprint=fingerprint
           - return NEW_ACTIVE, superseded=old
        """
        new_version_id = fingerprint
        now_ts = int(time.time())
        
        with self.control_plane.get_connection() as conn:
            # Start transaction
            conn.execute("BEGIN")
            
            try:
                # Get current document state
                cursor = conn.execute("""
                    SELECT active_version_id, last_seen_fingerprint 
                    FROM documents WHERE document_id = ?
                """, (document_id,))
                row = cursor.fetchone()
                
                if not row:
                    # Document doesn't exist (should not happen if called after get_or_create_document)
                    conn.execute("ROLLBACK")
                    raise ValueError(f"Document {document_id} not found")
                
                active_version_id, last_seen_fingerprint = row
                
                # Case: Already active
                if last_seen_fingerprint == fingerprint and active_version_id == new_version_id:
                    conn.commit()
                    return VersionDecisionResult(
                        decision=VersionDecision.ALREADY_ACTIVE,
                        new_version_id=new_version_id
                    )
                
                # Insert new version
                conn.execute("""
                    INSERT INTO document_versions 
                    (version_id, document_id, fingerprint, status, created_at)
                    VALUES (?, ?, ?, 'ACTIVE', ?)
                """, (new_version_id, document_id, fingerprint, now_ts))
                
                # Update document
                conn.execute("""
                    UPDATE documents 
                    SET active_version_id = ?, 
                        last_seen_fingerprint = ?,
                        updated_at = ?
                    WHERE document_id = ?
                """, (new_version_id, fingerprint, now_ts, document_id))
                
                superseded_version_id = None
                
                # If there was a previous active version, supersede it
                if active_version_id and active_version_id != new_version_id:
                    superseded_version_id = active_version_id
                    conn.execute("""
                        UPDATE document_versions 
                        SET status = 'SUPERSEDED',
                            superseded_by_version_id = ?,
                            archived_at = ?
                        WHERE version_id = ?
                    """, (new_version_id, now_ts, active_version_id))
                
                conn.commit()
                
                return VersionDecisionResult(
                    decision=VersionDecision.NEW_ACTIVE,
                    new_version_id=new_version_id,
                    superseded_version_id=superseded_version_id
                )
                
            except Exception:
                conn.execute("ROLLBACK")
                raise
    
    def claim_stage(
        self, version_id: str, stage: Stage, worker_id: str,
        now: int, ttl_seconds: int
    ) -> ClaimResultData:
        """Claim a stage for processing.
        
        Algorithm from plan 3.1.4:
        1) Read version_stage_state by (version_id, stage)
        2) If not exists:
           - Insert IN_PROGRESS with owner=worker_id, updated_at=now
           - return CLAIMED
        3) If status==DONE → should_process=false, reason=DONE
        4) If status==IN_PROGRESS:
           - If now - updated_at <= ttl_seconds → should_process=false, reason=IN_PROGRESS_RECENT
           - Else: Update owner=worker_id, updated_at=now (reclaim)
             should_process=true, reason=RECLAIMED_STALE
        5) If status==FAILED:
           - permit retry only if attempt < max_attempts
           - if permitted: set IN_PROGRESS and return CLAIMED
           - if not: should_process=false (dead)
        """
        max_attempts = 3  # Configurable
        
        with self.control_plane.get_connection() as conn:
            conn.execute("BEGIN")
            
            try:
                # Read current state
                cursor = conn.execute("""
                    SELECT status, attempt, updated_at 
                    FROM version_stage_state 
                    WHERE version_id = ? AND stage = ?
                """, (version_id, stage.value))
                row = cursor.fetchone()
                
                # Case 1: No existing state
                if not row:
                    conn.execute("""
                        INSERT INTO version_stage_state 
                        (version_id, stage, status, owner, attempt, updated_at)
                        VALUES (?, ?, 'IN_PROGRESS', ?, 1, ?)
                    """, (version_id, stage.value, worker_id, now))
                    conn.commit()
                    return ClaimResultData(
                        should_process=True,
                        reason=ClaimResult.CLAIMED
                    )
                
                status, attempt, updated_at = row
                
                # Case 2: Already DONE
                if status == "DONE":
                    conn.commit()
                    return ClaimResultData(
                        should_process=False,
                        reason=ClaimResult.DONE
                    )
                
                # Case 3: IN_PROGRESS
                if status == "IN_PROGRESS":
                    if now - updated_at <= ttl_seconds:
                        conn.commit()
                        return ClaimResultData(
                            should_process=False,
                            reason=ClaimResult.IN_PROGRESS_RECENT
                        )
                    else:
                        # Reclaim stale job
                        conn.execute("""
                            UPDATE version_stage_state 
                            SET owner = ?, updated_at = ?
                            WHERE version_id = ? AND stage = ?
                        """, (worker_id, now, version_id, stage.value))
                        conn.commit()
                        return ClaimResultData(
                            should_process=True,
                            reason=ClaimResult.RECLAIMED_STALE
                        )
                
                # Case 4: FAILED
                if status == "FAILED":
                    if attempt < max_attempts:
                        # Allow retry
                        conn.execute("""
                            UPDATE version_stage_state 
                            SET status = 'IN_PROGRESS',
                                owner = ?,
                                attempt = attempt + 1,
                                updated_at = ?
                            WHERE version_id = ? AND stage = ?
                        """, (worker_id, now, version_id, stage.value))
                        conn.commit()
                        return ClaimResultData(
                            should_process=True,
                            reason=ClaimResult.CLAIMED
                        )
                    else:
                        # Max retries exceeded
                        conn.commit()
                        return ClaimResultData(
                            should_process=False,
                            reason=ClaimResult.DONE  # Treat as done (dead)
                        )
                
                # Unknown status
                conn.commit()
                return ClaimResultData(
                    should_process=False,
                    reason=ClaimResult.DONE
                )
                
            except Exception:
                conn.execute("ROLLBACK")
                raise
    
    def mark_stage_done(self, version_id: str, stage: Stage, now: int) -> None:
        """Mark stage as successfully completed (upserts the row if not yet claimed)."""
        with self.control_plane.get_connection() as conn:
            conn.execute("""
                INSERT INTO version_stage_state (version_id, stage, status, owner, attempt, updated_at, error_last)
                VALUES (?, ?, 'DONE', NULL, 1, ?, NULL)
                ON CONFLICT(version_id, stage) DO UPDATE SET
                    status = 'DONE',
                    updated_at = excluded.updated_at,
                    error_last = NULL
            """, (version_id, stage.value, now))

    def mark_stage_failed(
        self, version_id: str, stage: Stage, now: int,
        error_summary: str
    ) -> None:
        """Mark stage as failed (upserts the row if not yet claimed)."""
        with self.control_plane.get_connection() as conn:
            conn.execute("""
                INSERT INTO version_stage_state (version_id, stage, status, owner, attempt, updated_at, error_last)
                VALUES (?, ?, 'FAILED', NULL, 1, ?, ?)
                ON CONFLICT(version_id, stage) DO UPDATE SET
                    status = 'FAILED',
                    updated_at = excluded.updated_at,
                    error_last = excluded.error_last
            """, (version_id, stage.value, now, error_summary))
    
    def register_artifact(
        self, version_id: str, artifact_kind: str,
        artifact_ref: str, expires_at: Optional[int] = None
    ) -> str:
        """Register an artifact."""
        artifact_id = f"{version_id}:{artifact_kind}:{int(time.time())}"
        now_ts = int(time.time())
        
        with self.control_plane.get_connection() as conn:
            conn.execute("""
                INSERT INTO artifacts 
                (artifact_id, version_id, artifact_kind, artifact_ref, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (artifact_id, version_id, artifact_kind, artifact_ref, now_ts, expires_at))
        
        return artifact_id
    
    def list_expired_artifacts(self, now: int) -> List[Artifact]:
        """List artifacts that have expired."""
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute("""
                SELECT version_id, artifact_kind, artifact_ref, expires_at
                FROM artifacts
                WHERE expires_at IS NOT NULL AND expires_at < ?
            """, (now,))
            
            artifacts = []
            for row in cursor.fetchall():
                artifacts.append(Artifact(
                    version_id=row[0],
                    artifact_kind=row[1],
                    artifact_ref=row[2],
                    expires_at=row[3]
                ))
            
            return artifacts
    
    def delete_artifact(self, artifact_id: str) -> None:
        """Delete an artifact."""
        with self.control_plane.get_connection() as conn:
            conn.execute("DELETE FROM artifacts WHERE artifact_id = ?", (artifact_id,))
    
    def get_stage_status(self, version_id: str, stage: Stage) -> Optional[Dict[str, Any]]:
        """Get current status of a stage."""
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute("""
                SELECT status, owner, attempt, updated_at, error_last
                FROM version_stage_state
                WHERE version_id = ? AND stage = ?
            """, (version_id, stage.value))

            row = cursor.fetchone()
            if not row:
                return None

            return {
                "status": row[0],
                "owner": row[1],
                "attempt": row[2],
                "updated_at": row[3],
                "error_last": row[4]
            }

    # -------------------------------------------------------------------------
    # File-skip decision (replaces FileCacheOperations + IdempotencyManager)
    # -------------------------------------------------------------------------

    def _compute_fingerprint(self, file_path: str, paranoid: bool = False) -> str:
        """Compute a file fingerprint.

        Fast path (default): "<size>:<mtime_ms>" — no file reads.
        Paranoid path: full SHA-256 of file content (used for deduplication).
        """
        stat = Path(file_path).stat()
        if not paranoid:
            return f"{stat.st_size}:{stat.st_mtime:.3f}"
        h = hashlib.sha256()
        with open(file_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()

    def should_skip_file(self, file_path: str) -> Tuple[bool, str]:
        """Answer whether this file should be skipped during ingestion.

        Returns:
            (skip, reason) where reason is one of:
              'cache_hit'  — file already fully ingested at this fingerprint
              'duplicate'  — identical content already ingested under another path
              'process'    — file must be (re)processed
        """
        try:
            # Fast fingerprint: size + mtime, no content read
            fast_fp = self._compute_fingerprint(file_path, paranoid=False)
            document_id = self.get_or_create_document(file_path)
            decision = self.ensure_version(document_id, fast_fp)

            if decision.decision == VersionDecision.ALREADY_ACTIVE:
                upsert = self.get_stage_status(decision.new_version_id, Stage.UPSERT)
                if upsert and upsert["status"] == "DONE":
                    return True, "cache_hit"

            # Content-level deduplication (only when file is new/changed)
            try:
                content_hash = self._compute_fingerprint(file_path, paranoid=True)
                canonical = self.find_duplicate(content_hash)
                if canonical and canonical != document_id:
                    return True, "duplicate"
                # Register this file as canonical for its content hash
                self.register_canonical(content_hash, document_id)
            except OSError as exc:
                log.debug("Could not compute content hash for %s: %s", file_path, exc)

            return False, "process"

        except Exception as exc:
            log.warning("should_skip_file failed for %s: %s — defaulting to process", file_path, exc)
            return False, "process"

    # -------------------------------------------------------------------------
    # Content deduplication
    # -------------------------------------------------------------------------

    def find_duplicate(self, content_hash: str) -> Optional[str]:
        """Return the canonical document_id for this content hash, or None."""
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute(
                "SELECT canonical_document_id FROM content_fingerprints WHERE fingerprint = ?",
                (content_hash,)
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def register_canonical(self, content_hash: str, document_id: str) -> None:
        """Register document_id as the canonical owner of this content hash.

        Uses INSERT OR IGNORE so that the first writer wins (stable canonical).
        """
        with self.control_plane.get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO content_fingerprints (fingerprint, canonical_document_id) VALUES (?, ?)",
                (content_hash, document_id)
            )