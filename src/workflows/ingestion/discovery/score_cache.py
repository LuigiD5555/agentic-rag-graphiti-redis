"""Persistent score cache for ingestion scanner.

Three-layer persistence:
  1. xattr on the file (fast, no DB round-trip)
  2. SQLite via LedgerRepository tables (file_scores, directory_scores)
  3. Mirror JSON under ~/.local/share/rag/scores/ when xattr unavailable

Scores:
  0 - nothing extractable (skip on next scan if mtime + exts_hash match)
  1 - has content (check ledger to decide whether to re-process)

The exts_hash ties all scores to the current extension/OCR configuration.
If the hash changes (user enables OCR, adds extensions, etc.) every lookup
returns None and files are re-evaluated automatically.
"""



import hashlib
import json
import os
import time
from pathlib import Path
from typing import Optional

from src.workflows.query.audit import get_logger

log = get_logger(__name__)

# xattr key names
_XATTR_SCORE = b"user.rag.file_score"
_XATTR_EXTS_HASH = b"user.rag.exts_hash"
_XATTR_CLASSIFIED_AT = b"user.rag.classified_at"

# Mirror directory for filesystems that do not support xattr
_MIRROR_DIR = Path.home() / ".local" / "share" / "rag" / "scores"

# Module-level lazy reference to LedgerRepository (avoids circular imports)
_ledger: Optional[object] = None


def _get_ledger():
    """Return the shared LedgerRepository instance, creating it if necessary."""
    global _ledger
    if _ledger is None:
        try:
            from src.ingestion.ledger.ledger_repository import LedgerRepository
            _ledger = LedgerRepository()
        except Exception as exc:
            log.debug("score_cache: cannot get LedgerRepository: %s", exc)
    return _ledger


# ---------------------------------------------------------------------------
# exts_hash
# ---------------------------------------------------------------------------

def compute_exts_hash(settings) -> str:
    """Compute a reproducible hash of the current extension / OCR configuration.

    Covers: DOCS_FILE_EXTS, ENABLE_OCR, and the built-in OCR extensions.
    If any of these change, all cached scores become stale.
    """
    exts = sorted(getattr(settings, "DOCS_FILE_EXTS", ()) or ())
    enable_ocr = bool(getattr(settings, "ENABLE_OCR", False))
    # OCR extensions are hardcoded in preprocessor; keep in sync with preprocessor.py
    ocr_exts = sorted([".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".pdf"])

    payload = json.dumps({
        "exts": exts,
        "enable_ocr": enable_ocr,
        "ocr_exts": ocr_exts if enable_ocr else [],
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# xattr helpers
# ---------------------------------------------------------------------------

def _xattr_get(path: str, key: bytes) -> Optional[bytes]:
    try:
        import xattr
        return xattr.getxattr(path, key)
    except Exception:
        return None


def _xattr_set(path: str, key: bytes, value: bytes) -> bool:
    try:
        import xattr
        xattr.setxattr(path, key, value)
        return True
    except Exception as exc:
        log.debug("score_cache: xattr write failed for %s: %s", path, exc)
        return False


def _read_score_from_xattr(path: str, current_mtime: float, current_exts_hash: str) -> Optional[int]:
    """Return score from xattr if valid, else None."""
    raw_score = _xattr_get(path, _XATTR_SCORE)
    if raw_score is None:
        return None
    raw_exts = _xattr_get(path, _XATTR_EXTS_HASH)
    if raw_exts is None:
        return None
    if raw_exts.decode(errors="replace") != current_exts_hash:
        return None
    # xattr does not store mtime; validate via filesystem stat
    try:
        actual_mtime = os.stat(path).st_mtime
        if abs(actual_mtime - current_mtime) > 1e-3:
            return None
    except OSError:
        return None
    try:
        return int(raw_score.decode())
    except (ValueError, UnicodeDecodeError):
        return None


def _write_score_to_xattr(path: str, score: int, exts_hash: str, classified_at: int) -> bool:
    ok = _xattr_set(path, _XATTR_SCORE, str(score).encode())
    ok = _xattr_set(path, _XATTR_EXTS_HASH, exts_hash.encode()) and ok
    ok = _xattr_set(path, _XATTR_CLASSIFIED_AT, str(classified_at).encode()) and ok
    return ok


# ---------------------------------------------------------------------------
# Mirror JSON helpers
# ---------------------------------------------------------------------------

def _mirror_path(abs_path: str) -> Path:
    key = hashlib.sha256(abs_path.encode()).hexdigest()[:16]
    return _MIRROR_DIR / f"{key}.json"


def _ensure_mirror_dir() -> None:
    try:
        _MIRROR_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        log.debug("score_cache: cannot create mirror dir: %s", exc)


def _read_score_from_mirror(path: str, current_mtime: float, current_exts_hash: str) -> Optional[int]:
    mp = _mirror_path(path)
    if not mp.exists():
        return None
    try:
        data = json.loads(mp.read_text())
        if data.get("abs_path") != path:
            return None
        if data.get("exts_hash") != current_exts_hash:
            return None
        try:
            actual_mtime = os.stat(path).st_mtime
            if abs(actual_mtime - current_mtime) > 1e-3:
                return None
        except OSError:
            return None
        return int(data["score"])
    except Exception as exc:
        log.debug("score_cache: mirror read failed for %s: %s", path, exc)
        return None


def _write_score_to_mirror(path: str, score: int, exts_hash: str, classified_at: int) -> None:
    _ensure_mirror_dir()
    mp = _mirror_path(path)
    try:
        mp.write_text(json.dumps({
            "abs_path": path,
            "score": score,
            "exts_hash": exts_hash,
            "classified_at": classified_at,
        }))
    except OSError as exc:
        log.debug("score_cache: mirror write failed for %s: %s", path, exc)


# ---------------------------------------------------------------------------
# SQLite helpers (via LedgerRepository)
# ---------------------------------------------------------------------------

def _read_file_score_from_sqlite(path: str, current_mtime: float, current_exts_hash: str) -> Optional[int]:
    ledger = _get_ledger()
    if ledger is None:
        return None
    try:
        with ledger.control_plane.get_connection() as conn:
            cursor = conn.execute(
                "SELECT score, file_mtime, exts_hash FROM file_scores WHERE abs_path = ?",
                (path,)
            )
            row = cursor.fetchone()
            if row is None:
                return None
            score, stored_mtime, stored_exts = row
            if stored_exts != current_exts_hash:
                return None
            if abs(stored_mtime - current_mtime) > 1e-3:
                return None
            return int(score)
    except Exception as exc:
        log.debug("score_cache: SQLite file read failed for %s: %s", path, exc)
        return None


def _write_file_score_to_sqlite(
    path: str, file_mtime: float, score: int, reason: str, exts_hash: str, classified_at: int
) -> None:
    ledger = _get_ledger()
    if ledger is None:
        return
    try:
        with ledger.control_plane.get_connection() as conn:
            conn.execute("""
                INSERT INTO file_scores (abs_path, file_mtime, score, reason, exts_hash, classified_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(abs_path) DO UPDATE SET
                    file_mtime = excluded.file_mtime,
                    score = excluded.score,
                    reason = excluded.reason,
                    exts_hash = excluded.exts_hash,
                    classified_at = excluded.classified_at
            """, (path, file_mtime, score, reason, exts_hash, classified_at))
    except Exception as exc:
        log.debug("score_cache: SQLite file write failed for %s: %s", path, exc)


# ---------------------------------------------------------------------------
# Public API — file scores
# ---------------------------------------------------------------------------

def get_file_score(abs_path: str, current_mtime: float, current_exts_hash: str) -> Optional[int]:
    """Return the cached score (0 or 1) if valid, else None.

    Lookup order: xattr → SQLite → mirror.
    Returns None if no valid score exists or if the file changed / config changed.
    """
    # Layer 1: xattr (fastest, no I/O beyond stat)
    score = _read_score_from_xattr(abs_path, current_mtime, current_exts_hash)
    if score is not None:
        return score

    # Layer 2: SQLite
    score = _read_file_score_from_sqlite(abs_path, current_mtime, current_exts_hash)
    if score is not None:
        return score

    # Layer 3: mirror JSON
    return _read_score_from_mirror(abs_path, current_mtime, current_exts_hash)


def set_file_score(
    abs_path: str,
    file_mtime: float,
    score: int,
    reason: str,
    exts_hash: str,
) -> None:
    """Persist the score for a file across all available layers."""
    classified_at = int(time.time())

    # Layer 1: xattr (best-effort, never blocks)
    xattr_ok = _write_score_to_xattr(abs_path, score, exts_hash, classified_at)

    # Layer 2: SQLite (always attempt)
    _write_file_score_to_sqlite(abs_path, file_mtime, score, reason, exts_hash, classified_at)

    # Layer 3: mirror only if xattr failed
    if not xattr_ok:
        _write_score_to_mirror(abs_path, score, exts_hash, classified_at)


# ---------------------------------------------------------------------------
# Public API — directory scores
# ---------------------------------------------------------------------------

def get_dir_score(
    abs_path: str, current_dir_mtime: float, current_exts_hash: str
) -> Optional[tuple[int, list[str]]]:
    """Return (score, extractable_paths) if valid, else None.

    Only consults SQLite (directories do not get xattr in this design).
    """
    ledger = _get_ledger()
    if ledger is None:
        return None
    try:
        with ledger.control_plane.get_connection() as conn:
            cursor = conn.execute(
                "SELECT score, extractable_paths, dir_mtime, exts_hash "
                "FROM directory_scores WHERE abs_path = ?",
                (abs_path,)
            )
            row = cursor.fetchone()
            if row is None:
                return None
            score, extractable_json, stored_mtime, stored_exts = row
            if stored_exts != current_exts_hash:
                return None
            if abs(stored_mtime - current_dir_mtime) > 1e-3:
                return None
            paths: list[str] = json.loads(extractable_json) if extractable_json else []
            return int(score), paths
    except Exception as exc:
        log.debug("score_cache: SQLite dir read failed for %s: %s", abs_path, exc)
        return None


def set_dir_score(
    abs_path: str,
    dir_mtime: float,
    score: int,
    extractable_paths: list[str],
    exts_hash: str,
) -> None:
    """Persist directory score into SQLite."""
    ledger = _get_ledger()
    if ledger is None:
        return
    classified_at = int(time.time())
    try:
        with ledger.control_plane.get_connection() as conn:
            conn.execute("""
                INSERT INTO directory_scores
                    (abs_path, dir_mtime, score, extractable_paths, exts_hash, classified_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(abs_path) DO UPDATE SET
                    dir_mtime = excluded.dir_mtime,
                    score = excluded.score,
                    extractable_paths = excluded.extractable_paths,
                    exts_hash = excluded.exts_hash,
                    classified_at = excluded.classified_at
            """, (abs_path, dir_mtime, score, json.dumps(extractable_paths), exts_hash, classified_at))
    except Exception as exc:
        log.debug("score_cache: SQLite dir write failed for %s: %s", abs_path, exc)


# ---------------------------------------------------------------------------
# Invalidation
# ---------------------------------------------------------------------------

def invalidate_all_scores() -> tuple[int, int]:
    """Delete all file_scores and directory_scores rows from SQLite.

    Returns (file_rows_deleted, dir_rows_deleted).
    Used by --reclassify; xattr/mirror scores are invalidated implicitly
    because a fresh exts_hash will not match the stored one.
    """
    ledger = _get_ledger()
    if ledger is None:
        log.warning("score_cache: cannot invalidate – LedgerRepository unavailable")
        return 0, 0
    try:
        with ledger.control_plane.get_connection() as conn:
            cur_f = conn.execute("DELETE FROM file_scores")
            cur_d = conn.execute("DELETE FROM directory_scores")
            return cur_f.rowcount, cur_d.rowcount
    except Exception as exc:
        log.warning("score_cache: invalidation failed: %s", exc)
        return 0, 0


__all__ = [
    "compute_exts_hash",
    "get_file_score",
    "set_file_score",
    "get_dir_score",
    "set_dir_score",
    "invalidate_all_scores",
]
