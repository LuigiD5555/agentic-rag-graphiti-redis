"""Pareto 80/20 compression for conversation history.

Implements intelligent compression that keeps 20% of content while
preserving 80% of meaning.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def identify_turning_points(messages: list[dict]) -> list[int]:
    """Identify key turning points in conversation.

    Turning points are:
    - First message
    - Last message
    - Messages with questions
    - Messages mentioning tools/documents
    - Messages with decisions/confirmations

    Args:
        messages: List of message dicts with 'role' and 'content'

    Returns:
        List of indices to keep
    """
    if not messages:
        return []

    indices = set()

    # Always keep first and last
    indices.add(0)
    indices.add(len(messages) - 1)

    for i, msg in enumerate(messages):
        content = msg.get("content", "").lower()

        # Questions (important for context)
        if "?" in content:
            indices.add(i)

        # Tool/document references
        if any(keyword in content for keyword in [
            "document", "file", "pdf", "excel", "office",
            "ocr", "archive", "extract", "convert"
        ]):
            indices.add(i)

        # Decisions/confirmations
        if any(keyword in content for keyword in [
            "yes", "no", "confirm", "proceed", "continue",
            "cancel", "stop", "done", "finish"
        ]):
            indices.add(i)

        # Error messages
        if any(keyword in content for keyword in [
            "error", "fail", "problem", "issue", "wrong"
        ]):
            indices.add(i)

    return sorted(list(indices))


def compress_messages(
    messages: list[dict],
    target_ratio: float = 0.2
) -> list[dict]:
    """Compress messages keeping target_ratio of most important.

    Args:
        messages: List of message dicts
        target_ratio: Fraction to keep (0.2 = keep 20%)

    Returns:
        Compressed list of messages
    """
    if not messages:
        return []

    if len(messages) <= 3:
        # Too few to compress meaningfully
        return messages

    # Calculate target count
    target_count = max(3, int(len(messages) * target_ratio))

    # Identify turning points
    important_indices = identify_turning_points(messages)

    # If we have more turning points than target, keep first/last + sample
    if len(important_indices) > target_count:
        # Always keep first and last
        keep_indices = {0, len(messages) - 1}

        # Sample from middle turning points
        middle = [i for i in important_indices if i not in keep_indices]
        step = max(1, len(middle) // (target_count - 2))
        keep_indices.update(middle[::step][:target_count - 2])

        important_indices = sorted(list(keep_indices))

    # Extract compressed messages
    compressed = [messages[i] for i in important_indices]

    logger.info(
        f"Compressed {len(messages)} messages to {len(compressed)} "
        f"({len(compressed)/len(messages)*100:.1f}%)"
    )

    return compressed


def format_compressed_summary(messages: list[dict]) -> str:
    """Format compressed messages into readable summary.

    Args:
        messages: Compressed message list

    Returns:
        Human-readable summary string
    """
    if not messages:
        return ""

    lines = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")

        # Truncate very long messages
        if len(content) > 200:
            content = content[:197] + "..."

        lines.append(f"{role}: {content}")

    return "\n".join(lines)


def compress_conversation(
    messages: list[dict],
    max_tokens: int = 500
) -> str:
    """Compress conversation to ~max_tokens preserving key information.

    This is the main entry point for Pareto compression.

    Args:
        messages: Full message history
        max_tokens: Target token budget (~4 chars = 1 token)

    Returns:
        Compressed summary string
    """
    if not messages:
        return ""

    # Calculate target character count (rough estimate: 4 chars = 1 token)
    max_chars = max_tokens * 4

    # Compress to ~20% of messages
    compressed = compress_messages(messages, target_ratio=0.2)

    # Format as summary
    summary = format_compressed_summary(compressed)

    # If still too long, truncate individual messages more aggressively
    if len(summary) > max_chars:
        truncated = []
        for msg in compressed:
            content = msg.get("content", "")
            # More aggressive truncation
            max_msg_len = max_chars // len(compressed)
            if len(content) > max_msg_len:
                content = content[:max_msg_len - 3] + "..."
            truncated.append({"role": msg["role"], "content": content})

        summary = format_compressed_summary(truncated)

    logger.debug(f"Final summary: {len(summary)} chars (~{len(summary)//4} tokens)")

    return summary