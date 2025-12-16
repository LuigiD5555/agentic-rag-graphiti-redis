"""Text utilities used during ingestion.

This module intentionally avoids network-dependent tokenization.

Background:
    Some tokenizers (notably `tiktoken`) can try to download tokenizer encoding
    files at runtime when a specific model encoding is requested. In offline or
    restricted network environments this breaks ingestion.

    For ingestion we mainly need a *conservative cap* so we do not send overly
    long text to the embedding endpoint. An approximate tokenizer is sufficient
    as long as it errs on the safe side (i.e., truncates earlier).

Approach:
    - Estimate tokens using a conservative character-to-token heuristic.
    - Truncate on whitespace boundaries when possible.
"""

import hashlib
import unicodedata
from typing import Optional

from src import logger


def sanitize_text(text: str) -> str:
    """Normalize and sanitize text for ingestion.

    Args:
        text: Raw input text.

    Returns:
        A normalized UTF-8 string with non-printable characters replaced.
    """
    normalized = unicodedata.normalize("NFC", str(text))
    encoded = normalized.encode("utf-8", errors="replace").decode("utf-8")
    return "".join(char if (char.isprintable() or char in "\n\t") else " " for char in encoded)


def generate_hash(text: str) -> str:
    """Generate a stable SHA-256 hash for the given text.

    Args:
        text: Input text.

    Returns:
        A hexadecimal SHA-256 digest of the sanitized text.
    """
    sanitized = sanitize_text(text)
    return hashlib.sha256(sanitized.encode("utf-8")).hexdigest()


def generate_hash_presanitized(text: str) -> str:
    """Generate a stable SHA-256 hash for already-sanitized text.

    This version skips the sanitize_text() call, assuming the input
    has already been sanitized. Use this to avoid redundant sanitization.

    Args:
        text: Pre-sanitized input text.

    Returns:
        A hexadecimal SHA-256 digest.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def effective_limit(limit: int) -> int:
    """Compute a conservative token cap.

    This trims a safety margin (~10%, min 8, max 1/3 of limit) so the effective
    token limit remains safely below the hard maximum.

    Args:
        limit: Hard token limit.

    Returns:
        A smaller, conservative token limit.
    """
    if limit <= 0:
        return 0
    margin = max(8, int(limit * 0.1))
    margin = min(margin, max(1, limit // 3))
    return max(1, limit - margin)


def _estimate_token_count(text: str) -> int:
    """Estimate token count using a conservative heuristic.

    Notes:
        A common rule-of-thumb is ~4 characters per token for English-like text.
        To remain conservative across languages and punctuation-heavy content,
        we assume ~3 characters per token. This will *overestimate* token count
        and truncate earlier, which is safer for embeddings.

    Args:
        text: Input text.

    Returns:
        Estimated token count.
    """
    cleaned = sanitize_text(text)
    if not cleaned:
        return 0

    # Count characters excluding common whitespace to avoid underestimating.
    non_whitespace_characters = sum(1 for char in cleaned if not char.isspace())
    return max(1, non_whitespace_characters // 3)


def truncate_to_token_limit(text: str, limit: int, model_name: Optional[str]) -> str:
    """Truncate text to stay under a token limit without online tokenizers.

    Args:
        text: Input text.
        limit: Maximum allowed tokens.
        model_name: Model name (kept for API compatibility; not used by default).

    Returns:
        Possibly truncated text.
    """
    _ = model_name  # model_name is intentionally unused to keep the function offline-safe.

    if limit <= 0:
        return text

    estimated_tokens = _estimate_token_count(text)
    if estimated_tokens <= limit:
        return text

    # Convert token budget to a conservative character budget.
    # We assume 3 chars per token; keep a small extra margin for safety.
    max_non_whitespace_characters = max(1, int(limit * 3 * 0.95))

    cleaned = sanitize_text(text)
    current_non_whitespace = 0
    cutoff_index = 0

    for index, char in enumerate(cleaned):
        if not char.isspace():
            current_non_whitespace += 1
        cutoff_index = index + 1
        if current_non_whitespace >= max_non_whitespace_characters:
            break

    truncated = cleaned[:cutoff_index]

    # Prefer a clean cut at whitespace if we can find it close to the end.
    last_whitespace = truncated.rfind(" ")
    if last_whitespace > 0 and (len(truncated) - last_whitespace) < 100:
        truncated = truncated[:last_whitespace]

    logger.debug(
        "Embedding text truncated (estimated_tokens=%d -> limit=%d, chars=%d -> %d)",
        estimated_tokens,
        limit,
        len(cleaned),
        len(truncated),
    )
    return truncated


def truncate_to_token_limit_presanitized(text: str, limit: int, model_name: Optional[str]) -> str:
    """Truncate already-sanitized text to stay under a token limit.

    This version skips the sanitize_text() call, assuming the input
    has already been sanitized. Use this to avoid redundant sanitization.

    Args:
        text: Pre-sanitized input text.
        limit: Maximum allowed tokens.
        model_name: Model name (kept for API compatibility; not used).

    Returns:
        Possibly truncated text.
    """
    _ = model_name  # Intentionally unused to keep the function offline-safe.

    if limit <= 0:
        return text

    # Estimate tokens on the presanitized text (skip sanitize in _estimate_token_count)
    if not text:
        return text

    non_whitespace_characters = sum(1 for char in text if not char.isspace())
    estimated_tokens = max(1, non_whitespace_characters // 3)

    if estimated_tokens <= limit:
        return text

    # Convert token budget to a conservative character budget.
    max_non_whitespace_characters = max(1, int(limit * 3 * 0.95))

    current_non_whitespace = 0
    cutoff_index = 0

    for index, char in enumerate(text):
        if not char.isspace():
            current_non_whitespace += 1
        cutoff_index = index + 1
        if current_non_whitespace >= max_non_whitespace_characters:
            break

    truncated = text[:cutoff_index]

    # Prefer a clean cut at whitespace if we can find it close to the end.
    last_whitespace = truncated.rfind(" ")
    if last_whitespace > 0 and (len(truncated) - last_whitespace) < 100:
        truncated = truncated[:last_whitespace]

    logger.debug(
        "Embedding text truncated (estimated_tokens=%d -> limit=%d, chars=%d -> %d)",
        estimated_tokens,
        limit,
        len(text),
        len(truncated),
    )
    return truncated


__all__ = [
    "sanitize_text",
    "generate_hash",
    "generate_hash_presanitized",
    "truncate_to_token_limit",
    "truncate_to_token_limit_presanitized",
    "effective_limit",
]
