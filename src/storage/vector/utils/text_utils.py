from __future__ import annotations

import hashlib
import unicodedata
from typing import Optional

from src import logger

try:
    import tiktoken  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    tiktoken = None


def sanitize_text(text: str) -> str:
    normalized = unicodedata.normalize("NFC", str(text))
    encoded = normalized.encode("utf-8", errors="replace").decode("utf-8")
    return "".join(char if (char.isprintable() or char in "\n\t") else " " for char in encoded)


def generate_hash(text: str) -> str:
    sanitized = sanitize_text(text)
    return hashlib.sha256(sanitized.encode("utf-8")).hexdigest()


def effective_limit(limit: int) -> int:
    """
    Compute a conservative token cap: trim a margin (~10%, min 8, max 1/3 of limit).
    """
    if limit <= 0:
        return 0
    margin = max(8, int(limit * 0.1))
    margin = min(margin, max(1, limit // 3))
    return max(1, limit - margin)


def truncate_to_token_limit(text: str, limit: int, model_name: Optional[str]) -> str:
    """
    Ensure text stays under the embedding token limit. Prefer whitespace for tiny limits.
    """
    if limit <= 0:
        return text

    # If we don't know the tokenizer model, be conservative and use whitespace tokens.
    # This avoids under-counting vs GGUF/llama tokenizers.
    if model_name is None or limit <= 8 or tiktoken is None:
        tokens = text.split()
        if len(tokens) <= limit:
            return text
        return " ".join(tokens[:limit])

    try:
        enc = tiktoken.encoding_for_model(model_name) if model_name else tiktoken.get_encoding("cl100k_base")
    except Exception:
        enc = tiktoken.get_encoding("cl100k_base")

    token_ids = enc.encode(text)
    if len(token_ids) <= limit:
        return text

    truncated = enc.decode(token_ids[:limit])
    if len(token_ids) > limit:
        logger.debug("Embedding text truncated from %d to %d tokens", len(token_ids), limit)
    return truncated


__all__ = ["sanitize_text", "generate_hash", "truncate_to_token_limit", "effective_limit"]
