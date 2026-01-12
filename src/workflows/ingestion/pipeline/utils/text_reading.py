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
    encodings: Sequence[str] = (
        "utf-8",           # Universal, supports all languages
        "utf-16",          # Common in Windows for Asian languages
        "utf-16-le",       # Little-endian UTF-16
        "utf-16-be",       # Big-endian UTF-16
        "gb18030",         # Chinese (Simplified) - superset of GBK and GB2312
        "gbk",             # Chinese (Simplified) - common encoding
        "big5",            # Chinese (Traditional)
        "shift_jis",       # Japanese
        "euc-jp",          # Japanese (Extended Unix Code)
        "iso-2022-jp",     # Japanese (email/legacy)
        "euc-kr",          # Korean
        "cp949",           # Korean (Windows)
        "koi8-r",          # Russian (Cyrillic)
        "cp1251",          # Russian/Cyrillic (Windows)
        "iso-8859-5",      # Russian/Cyrillic
        "cp1256",          # Arabic (Windows)
        "iso-8859-6",      # Arabic
        "cp1252",          # Western European (Windows)
        "latin-1",         # ISO-8859-1 (fallback)
        "ascii",           # Strict ASCII (last resort)
    ),
    max_probe_bytes: int = 8192,
) -> TextReadResult:
    """Read a file as text with encoding fallbacks supporting multiple languages.

    Supports a wide range of encodings including:
    - UTF-8/16: Universal Unicode encodings
    - Chinese: GB18030, GBK, Big5
    - Japanese: Shift-JIS, EUC-JP, ISO-2022-JP
    - Korean: EUC-KR, CP949
    - Russian: KOI8-R, CP1251, ISO-8859-5
    - Arabic: CP1256, ISO-8859-6
    - Western: CP1252, Latin-1

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
            # Try decoding with the current encoding
            text = data.decode(encoding)
            # Additional validation: ensure no surrogate characters leaked through
            text = text.encode('utf-8', errors='surrogatepass').decode('utf-8', errors='ignore')
            return TextReadResult(text=text, encoding=encoding)
        except (UnicodeDecodeError, LookupError) as exc:
            # LookupError: unknown encoding name
            last_error = exc if isinstance(exc, UnicodeDecodeError) else last_error
            continue

    assert last_error is not None
    raise last_error


def normalize_patterns(entries: Iterable[object]) -> list[str]:
    return [str(e).strip() for e in entries if str(e).strip()]
