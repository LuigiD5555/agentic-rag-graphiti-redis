"""Helpers for reading text files robustly during ingestion.

Goal: avoid failing a whole ingestion run due to a single file with a weird encoding
or binary content disguised as text.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


@dataclass(frozen=True)
class TextReadResult:
    text: str
    encoding: str


def looks_binary(data: bytes, *, suspicious_ratio: float = 0.30) -> bool:
    """Heuristic check for binary-ish data.

    - Treat NUL as binary.
    - Treat a high ratio of control bytes as binary.
    """
    if not data:
        return False
    if b"\x00" in data:
        return True

    suspicious = 0
    for byte in data:
        if byte in (9, 10, 13):  # \t, \n, \r
            continue
        if 32 <= byte <= 126:  # common printable ASCII
            continue
        if 160 <= byte <= 255:  # extended bytes are common in cp1252/latin-1
            continue
        suspicious += 1

    return (suspicious / max(1, len(data))) >= suspicious_ratio


def read_text_with_fallbacks(
    path: str | Path,
    *,
    encodings: Sequence[str] = ("utf-8", "cp1252", "latin-1"),
    max_probe_bytes: int = 8192,
) -> TextReadResult:
    """Read a file as text with encoding fallbacks.

    Raises:
        UnicodeDecodeError: if all decoding attempts fail.
        ValueError: if the file looks binary.
    """
    file_path = Path(path)
    data = file_path.read_bytes()

    probe = data[:max_probe_bytes]
    if looks_binary(probe):
        raise ValueError("binary-like content")

    last_error: UnicodeDecodeError | None = None
    for encoding in encodings:
        try:
            return TextReadResult(text=data.decode(encoding), encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
            continue

    assert last_error is not None
    raise last_error


def normalize_patterns(entries: Iterable[object]) -> list[str]:
    return [str(e).strip() for e in entries if str(e).strip()]
