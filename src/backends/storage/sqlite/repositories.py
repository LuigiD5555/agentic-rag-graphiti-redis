"""Repository implementations for SQLite control plane.

This module provides the repository layer for:
- ScanCheckpointStore: Scan checkpointing and resumibility
- FileMetadataStore: File metadata and phase status tracking
- ChunkRegistryStore: Chunk registry and idempotence
- SessionRepository: Session preferences (privacy switch)
- AuditRepository: Audit events
"""

import json
import time
import hashlib
from typing import Optional, List, Dict, Any
from enum import Enum

from . import (
    SQLiteControlPlane,
    ScanRunStatus,
    FileStatus,
    ChunkStatus,
    UserSession,
    AuditEvent
)
from src import logger


class ProcessingDecision(Enum):
    """Decision for file processing."""
    PROCESS = "PROCESS"
    SKIP = "SKIP"
    RETRY = "RETRY"


class ScanCheckpointStore:
    """Repository for scan checkpointing operations."""
    
    def __init__(self, control_plane: SQLiteControlPlane):
        self.control_plane = control_plane
    
    def create_run(self, root_paths: List[str], options_hash: str, now_ts: int) -> str:
        """Create a new scan run."""
        import uuid
        run_id = f"scan_{int(now_ts)}_{uuid.uuid4().hex[:8]}"
        
        with self.control_plane.get_connection() as conn:
            conn.execute("""
                INSERT INTO scan_runs 
                (run_id, root_paths_json, options_hash, status, started_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                run_id,
                json.dumps(root_paths),
                options_hash,
                ScanRunStatus.NEW.value,
                now_ts,
                now_ts
            ))
        
        logger.info(f"Created scan run {run_id}")
        return run_id
    
    def resume_run(self, run_id: str) -> Dict[str, Any]:
        """Resume an existing scan run."""
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute("""
                SELECT run_id, root_paths_json, options_hash, status, 
                       started_at, updated_at, dirs_visited, files_found, last_error
                FROM scan_runs WHERE run_id = ?
            """, (run_id,))
            
            row = cursor.fetchone()
            if not row:
                raise ValueError(f"Scan run {run_id} not found")
            
            # Get pending directories
            pending_cursor = conn.execute("""
                SELECT dir_path FROM scan_pending 
                WHERE run_id = ? ORDER BY seq
            """, (run_id,))
            pending_dirs = [row[0] for row in pending_cursor.fetchall()]
            
            # Get visited directories
            visited_cursor = conn.execute("""
                SELECT dir_path FROM scan_visited WHERE run_id = ?
            """, (run_id,))
            visited_dirs = [row[0] for row in visited_cursor.fetchall()]
            
            # Get discovered files
            files_cursor = conn.execute("""
                SELECT file_path FROM scan_files WHERE run_id = ? ORDER BY seq
            """, (run_id,))
            discovered_files = [row[0] for row in files_cursor.fetchall()]
            
            return {
                "run_id": row[0],
                "root_paths": json.loads(row[1]),
                "options_hash": row[2],
                "status": ScanRunStatus(row[3]),
                "started_at": row[4],
                "updated_at": row[5],
                "dirs_visited": row[6],
                "files_found": row[7],
                "last_error": row[8],
                "pending_dirs": pending_dirs,
                "visited_dirs": visited_dirs,
                "discovered_files": discovered_files
            }
    
    def enqueue_dir(self, run_id: str, dir_path: str, now_ts: int) -> None:
        """Enqueue a directory for scanning."""
        with self.control_plane.get_connection() as conn:
            # Get next sequence number
            cursor = conn.execute("""
                SELECT COALESCE(MAX(seq), 0) FROM scan_pending WHERE run_id = ?
            """, (run_id,))
            seq = cursor.fetchone()[0] + 1
            
            conn.execute("""
                INSERT OR IGNORE INTO scan_pending (run_id, seq, dir_path, enqueued_at)
                VALUES (?, ?, ?, ?)
            """, (run_id, seq, dir_path, now_ts))
    
    def dequeue_dir(self, run_id: str) -> Optional[str]:
        """Dequeue the next directory to scan."""
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute("""
                SELECT dir_path FROM scan_pending 
                WHERE run_id = ? ORDER BY seq LIMIT 1
            """, (run_id,))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            dir_path = row[0]
            
            # Remove from pending
            conn.execute("""
                DELETE FROM scan_pending WHERE run_id = ? AND dir_path = ?
            """, (run_id, dir_path))
            
            return dir_path
    
    def mark_visited(self, run_id: str, dir_path: str, now_ts: int) -> None:
        """Mark a directory as visited."""
        with self.control_plane.get_connection() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO scan_visited (run_id, dir_path, visited_at)
                VALUES (?, ?, ?)
            """, (run_id, dir_path, now_ts))
            
            # Update counters
            conn.execute("""
                UPDATE scan_runs 
                SET dirs_visited = dirs_visited + 1, updated_at = ?
                WHERE run_id = ?
            """, (now_ts, run_id))
    
    def add_found_file(self, run_id: str, file_path: str, now_ts: int) -> None:
        """Add a discovered file."""
        with self.control_plane.get_connection() as conn:
            # Get next sequence number
            cursor = conn.execute("""
                SELECT COALESCE(MAX(seq), 0) FROM scan_files WHERE run_id = ?
            """, (run_id,))
            seq = cursor.fetchone()[0] + 1
            
            conn.execute("""
                INSERT OR IGNORE INTO scan_files (run_id, seq, file_path, found_at)
                VALUES (?, ?, ?, ?)
            """, (run_id, seq, file_path, now_ts))
            
            # Update counters
            conn.execute("""
                UPDATE scan_runs 
                SET files_found = files_found + 1, updated_at = ?
                WHERE run_id = ?
            """, (now_ts, run_id))
    
    def set_run_status(self, run_id: str, status: ScanRunStatus, now_ts: int, error: Optional[str] = None) -> None:
        """Update scan run status."""
        with self.control_plane.get_connection() as conn:
            conn.execute("""
                UPDATE scan_runs 
                SET status = ?, updated_at = ?, last_error = ?
                WHERE run_id = ?
            """, (status.value, now_ts, error, run_id))


class FileMetadataStore:
    """Repository for file metadata and processing status."""
    
    def __init__(self, control_plane: SQLiteControlPlane):
        self.control_plane = control_plane
    
    def _compute_fingerprint_hash(self, file_path: str, mtime_ns: int, size_bytes: int) -> str:
        """Compute fingerprint hash for a file."""
        fingerprint_data = f"{file_path}:{mtime_ns}:{size_bytes}"
        return hashlib.sha256(fingerprint_data.encode()).hexdigest()
    
    def upsert_fingerprint(self, file_path: str, mtime_ns: int, size_bytes: int,
                           content_hash: Optional[str], now_ts: int) -> None:
        """Upsert file fingerprint."""
        fingerprint_hash = self._compute_fingerprint_hash(file_path, mtime_ns, size_bytes)
        
        with self.control_plane.get_connection() as conn:
            conn.execute(
                """
                INSERT INTO files
                (file_path, mtime_ns, size_bytes, content_hash, fingerprint_hash,
                 status, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    mtime_ns = excluded.mtime_ns,
                    size_bytes = excluded.size_bytes,
                    content_hash = excluded.content_hash,
                    fingerprint_hash = excluded.fingerprint_hash,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    file_path,
                    mtime_ns,
                    size_bytes,
                    content_hash,
                    fingerprint_hash,
                    FileStatus.NEW.value,
                    now_ts,
                ),
            )
    
    def decide_processing(self, file_path: str, mtime_ns: int, size_bytes: int,
                          content_hash: Optional[str], now_ts: int) -> ProcessingDecision:
        """Decide whether to process, skip, or retry a file."""
        fingerprint_hash = self._compute_fingerprint_hash(file_path, mtime_ns, size_bytes)
        
        with self.control_plane.get_connection() as conn:
            # Check if file exists in database
            cursor = conn.execute("""
                SELECT status, fingerprint_hash, content_hash, last_error
                FROM files WHERE file_path = ?
            """, (file_path,))
            
            row = cursor.fetchone()
            
            if not row:
                # New file
                return ProcessingDecision.PROCESS
            
            status = FileStatus(row[0])
            stored_fingerprint = row[1]
            last_error = row[3]
            
            # Check if fingerprint changed
            if fingerprint_hash != stored_fingerprint:
                # File changed, need to reprocess
                return ProcessingDecision.PROCESS
            
            # Check if file is already fully processed
            if status == FileStatus.UPSERTED:
                return ProcessingDecision.SKIP

            if status == FileStatus.DELETED:
                return ProcessingDecision.SKIP
            
            # Check if file failed previously
            if status == FileStatus.FAILED:
                # Check if we should retry based on error and retry policy
                if last_error and "permanent" in last_error.lower():
                    return ProcessingDecision.SKIP
                return ProcessingDecision.RETRY
            
            # File is in intermediate state, continue processing
            return ProcessingDecision.PROCESS
    
    def set_status(self, file_path: str, new_status: FileStatus, now_ts: int,
                   error: Optional[str] = None) -> None:
        """Update file processing status."""
        with self.control_plane.get_connection() as conn:
            conn.execute("""
                UPDATE files 
                SET status = ?, updated_at = ?, last_error = ?
                WHERE file_path = ?
            """, (new_status.value, now_ts, error, file_path))


class ChunkRegistryStore:
    """Repository for chunk registry and idempotence."""
    
    def __init__(self, control_plane: SQLiteControlPlane):
        self.control_plane = control_plane
    
    def _compute_chunk_id(self, file_path: str, chunk_index: int, chunk_hash: str) -> str:
        """Compute stable chunk ID."""
        chunk_data = f"{file_path}:{chunk_index}:{chunk_hash}"
        return hashlib.sha256(chunk_data.encode()).hexdigest()
    
    def register_chunks(self, file_path: str, chunk_descriptors: List[Dict[str, Any]],
                        now_ts: int) -> List[str]:
        """Register chunks for a file."""
        chunk_ids = []
        
        with self.control_plane.get_connection() as conn:
            for desc in chunk_descriptors:
                chunk_index = desc["index"]
                chunk_hash = desc["hash"]
                chunk_id = self._compute_chunk_id(file_path, chunk_index, chunk_hash)
                
                conn.execute("""
                    INSERT OR IGNORE INTO chunks 
                    (chunk_id, file_path, chunk_index, chunk_hash, status, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (
                    chunk_id,
                    file_path,
                    chunk_index,
                    chunk_hash,
                    ChunkStatus.NEW.value,
                    now_ts
                ))
                
                chunk_ids.append(chunk_id)
        
        return chunk_ids
    
    def get_chunk_status(self, chunk_id: str) -> ChunkStatus:
        """Get chunk processing status."""
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute("""
                SELECT status FROM chunks WHERE chunk_id = ?
            """, (chunk_id,))
            
            row = cursor.fetchone()
            if not row:
                return ChunkStatus.NEW
            
            return ChunkStatus(row[0])
    
    def set_chunk_status(self, chunk_id: str, status: ChunkStatus, now_ts: int,
                         vector_id: Optional[str] = None, error: Optional[str] = None) -> None:
        """Update chunk processing status."""
        with self.control_plane.get_connection() as conn:
            if vector_id:
                conn.execute("""
                    UPDATE chunks 
                    SET status = ?, vector_id = ?, updated_at = ?, last_error = ?
                    WHERE chunk_id = ?
                """, (status.value, vector_id, now_ts, error, chunk_id))
            else:
                conn.execute("""
                    UPDATE chunks 
                    SET status = ?, updated_at = ?, last_error = ?
                    WHERE chunk_id = ?
                """, (status.value, now_ts, error, chunk_id))
    
    def increment_retry(self, chunk_id: str, now_ts: int) -> int:
        """Increment retry count for a chunk."""
        with self.control_plane.get_connection() as conn:
            conn.execute("""
                UPDATE chunks 
                SET retry_count = retry_count + 1, updated_at = ?
                WHERE chunk_id = ?
            """, (now_ts, chunk_id))
            
            cursor = conn.execute("""
                SELECT retry_count FROM chunks WHERE chunk_id = ?
            """, (chunk_id,))
            
            return cursor.fetchone()[0]


class SessionRepository:
    """Repository for user session preferences."""
    
    def __init__(self, control_plane: SQLiteControlPlane):
        self.control_plane = control_plane
    
    def get_or_create_session(self, session_id: str, now_ts: int) -> UserSession:
        """Get or create a user session."""
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute("""
                SELECT session_id, created_at, updated_at, llm_pii_allowed, 
                       llm_trust_label, preferred_answer_style, notes
                FROM user_sessions WHERE session_id = ?
            """, (session_id,))
            
            row = cursor.fetchone()
            
            if row:
                return UserSession(
                    session_id=row[0],
                    created_at=row[1],
                    updated_at=row[2],
                    llm_pii_allowed=bool(row[3]),
                    llm_trust_label=row[4],
                    preferred_answer_style=row[5],
                    notes=row[6]
                )
            else:
                # Create new session
                conn.execute("""
                    INSERT INTO user_sessions 
                    (session_id, created_at, updated_at, llm_pii_allowed, llm_trust_label)
                    VALUES (?, ?, ?, ?, ?)
                """, (session_id, now_ts, now_ts, 0, "untrusted"))
                
                return UserSession(
                    session_id=session_id,
                    created_at=now_ts,
                    updated_at=now_ts,
                    llm_pii_allowed=False,
                    llm_trust_label="untrusted"
                )
    
    def update_session(self, session_id: str, llm_pii_allowed: Optional[bool] = None,
                       llm_trust_label: Optional[str] = None,
                       preferred_answer_style: Optional[str] = None,
                       notes: Optional[str] = None, now_ts: Optional[int] = None) -> None:
        """Update session preferences."""
        if now_ts is None:
            now_ts = int(time.time())
        
        updates = []
        params = []
        
        if llm_pii_allowed is not None:
            updates.append("llm_pii_allowed = ?")
            params.append(1 if llm_pii_allowed else 0)
        
        if llm_trust_label is not None:
            updates.append("llm_trust_label = ?")
            params.append(llm_trust_label)
        
        if preferred_answer_style is not None:
            updates.append("preferred_answer_style = ?")
            params.append(preferred_answer_style)
        
        if notes is not None:
            updates.append("notes = ?")
            params.append(notes)
        
        if not updates:
            return
        
        updates.append("updated_at = ?")
        params.append(now_ts)
        params.append(session_id)
        
        with self.control_plane.get_connection() as conn:
            conn.execute(f"""
                UPDATE user_sessions 
                SET {', '.join(updates)}
                WHERE session_id = ?
            """, params)


class AuditRepository:
    """Repository for audit events."""
    
    def __init__(self, control_plane: SQLiteControlPlane):
        self.control_plane = control_plane
    
    def log_event(self, session_id: str, event_type: str, metadata: Dict[str, Any],
                  event_at: Optional[int] = None) -> str:
        """Log an audit event."""
        import uuid
        
        if event_at is None:
            event_at = int(time.time())
        
        event_id = f"audit_{event_at}_{uuid.uuid4().hex[:8]}"
        
        with self.control_plane.get_connection() as conn:
            conn.execute("""
                INSERT INTO audit_events 
                (event_id, session_id, event_type, event_at, metadata_json)
                VALUES (?, ?, ?, ?, ?)
            """, (
                event_id,
                session_id,
                event_type,
                event_at,
                json.dumps(metadata)
            ))
        
        return event_id
    
    def get_events(self, session_id: str, limit: int = 100) -> List[AuditEvent]:
        """Get audit events for a session."""
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute("""
                SELECT event_id, session_id, event_type, event_at, metadata_json
                FROM audit_events 
                WHERE session_id = ?
                ORDER BY event_at DESC
                LIMIT ?
            """, (session_id, limit))
            
            events = []
            for row in cursor.fetchall():
                events.append(AuditEvent(
                    event_id=row[0],
                    session_id=row[1],
                    event_type=row[2],
                    event_at=row[3],
                    metadata_json=row[4]
                ))
            
            return events
    
    def get_events_by_type(self, event_type: str, limit: int = 100) -> List[AuditEvent]:
        """Get audit events by type."""
        with self.control_plane.get_connection() as conn:
            cursor = conn.execute("""
                SELECT event_id, session_id, event_type, event_at, metadata_json
                FROM audit_events 
                WHERE event_type = ?
                ORDER BY event_at DESC
                LIMIT ?
            """, (event_type, limit))
            
            events = []
            for row in cursor.fetchall():
                events.append(AuditEvent(
                    event_id=row[0],
                    session_id=row[1],
                    event_type=row[2],
                    event_at=row[3],
                    metadata_json=row[4]
                ))
            
            return events
