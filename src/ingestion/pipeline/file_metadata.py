from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
import re
from typing import Any, Dict, Optional


def gather_file_metadata(path: Optional[str]) -> Dict[str, Any]:
    resolved = str(path or "").strip()
    if not resolved and hasattr(path, "strip"):
        resolved = str(path).strip()

    info: Dict[str, Any] = {
        "file_path": resolved or None,
        "file_name": os.path.basename(resolved) if resolved else None,
        "file_extension": os.path.splitext(resolved)[1].lower() if resolved else None,
        "parent_directory": os.path.dirname(resolved) if resolved else None,
        "file_size_bytes": None,
        "file_modified_at": None,
        "file_id": _generate_hash(resolved) if resolved else None,
    }

    if resolved and os.path.isfile(resolved):
        try:
            stats = os.stat(resolved)
            info["file_size_bytes"] = stats.st_size
            info["file_modified_at"] = datetime.fromtimestamp(stats.st_mtime, tz=timezone.utc).isoformat()
        except OSError:
            pass

    return info


def coerce_datetime(raw: str) -> Optional[str]:
    """Try to coerce various date representations into RFC3339 strings."""
    text = raw.strip()
    if not text:
        return None

    candidate = text[:-1] + "+00:00" if text.endswith("Z") else text

    coerced = _coerce_by_strptime(candidate)
    if coerced:
        return coerced

    coerced = _coerce_by_iso(candidate)
    if coerced:
        return coerced

    coerced = _coerce_pdf_timestamp(text)
    if coerced:
        return coerced

    return None


def _coerce_by_strptime(candidate: str) -> Optional[str]:
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            dt = datetime.strptime(candidate, fmt)
            dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            continue
    return None


def _coerce_by_iso(candidate: str) -> Optional[str]:
    try:
        dt = datetime.fromisoformat(candidate)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        return None


def _coerce_pdf_timestamp(text: str) -> Optional[str]:
    m = re.match(r"^D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?([Zz]|[+-]\d{2}'?\d{2}')?$", text)
    if not m:
        return None
    parts = m.groups()
    y = int(parts[0])
    month = int(parts[1] or "1")
    day = int(parts[2] or "1")
    hour = int(parts[3] or "0")
    minute = int(parts[4] or "0")
    second = int(parts[5] or "0")
    tz_raw = parts[6] or "Z"
    if tz_raw.upper() == "Z":
        tz = timezone.utc
    elif re.match(r"[+-]\d{2}'?\d{2}'?", tz_raw):
        sign = 1 if tz_raw.startswith("+") else -1
        digits = re.sub(r"[+'-]", "", tz_raw)
        offset_hours = int(digits[:2])
        offset_minutes = int(digits[2:4]) if len(digits) >= 4 else 0
        tz = timezone(sign * timedelta(hours=offset_hours, minutes=offset_minutes))
    else:
        tz = timezone.utc
    try:
        dt = datetime(y, month, day, hour, minute, second, tzinfo=tz)
        return dt.isoformat()
    except ValueError:
        return None


def _generate_hash(text: str) -> str:
    import hashlib

    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


__all__ = ["gather_file_metadata", "coerce_datetime"]
