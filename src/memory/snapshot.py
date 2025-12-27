"""Conversation snapshot creation for ChatMemory (cross-chat recall).

Implements Fase 4 del Plan Maestro:
- Compress conversations using Pareto 80/20
- Extract key quotes, keywords, summary
- Persist to Weaviate ChatMemory collection
"""
import json
import logging
import re
from datetime import datetime
from typing import List, Dict, Any

from src.memory.types import ChatMemorySnapshot
from src.memory.core.state import ConversationState
from src.memory.compression.pareto import compress_messages, format_compressed_summary
from src.memory.storage.chat_memory_schema import calculate_ttl_timestamp

logger = logging.getLogger(__name__)


def create_snapshot(
    state: ConversationState,
    user_id: str,
    thread_id: str,
    ttl_days: int = 30,
    pinned: bool = False,
) -> ChatMemorySnapshot:
    """Create compressed snapshot from conversation state.

    Args:
        state: Current conversation state
        user_id: User identifier
        thread_id: Thread identifier
        ttl_days: Days until expiration (default: 30)
        pinned: Protect from TTL cleanup (default: False)

    Returns:
        ChatMemorySnapshot ready for persistence
    """
    messages = state.get("messages", [])

    if not messages:
        logger.warning("Cannot create snapshot from empty conversation")
        # Return minimal snapshot
        return ChatMemorySnapshot(
            summary_dense="",
            key_quotes=[],
            keywords=[],
            thread_id=thread_id,
            user_id=user_id,
            timestamp=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            ttl_at=calculate_ttl_timestamp(ttl_days),
            pinned=pinned,
            original_message_count=0,
            compression_ratio=0.0,
            tool_executions=None,
        )

    logger.info(
        f"Creating snapshot for thread {thread_id[:8]}... "
        f"({len(messages)} messages)"
    )

    # 1. Compress messages using Pareto 80/20
    compressed = compress_messages(messages, target_ratio=0.2)
    summary_dense = format_compressed_summary(compressed)

    # 2. Extract key quotes
    key_quotes = extract_key_quotes(messages, max_quotes=5)

    # 3. Extract keywords for BM25
    keywords = extract_keywords(messages, max_keywords=20)

    # 4. Calculate compression ratio
    original_size = sum(len(msg.get("content", "")) for msg in messages)
    compressed_size = len(summary_dense)
    compression_ratio = (
        compressed_size / original_size if original_size > 0 else 0.0
    )

    # 5. Serialize tool executions (if any)
    tool_executions_json = None
    tool_execs = state.get("tool_executions", [])
    if tool_execs:
        try:
            tool_executions_json = json.dumps(tool_execs)
        except Exception as e:
            logger.warning(f"Could not serialize tool executions: {e}")

    # 6. Create snapshot
    snapshot = ChatMemorySnapshot(
        summary_dense=summary_dense,
        key_quotes=key_quotes,
        keywords=keywords,
        thread_id=thread_id,
        user_id=user_id,
        timestamp=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        ttl_at=calculate_ttl_timestamp(ttl_days),
        pinned=pinned,
        original_message_count=len(messages),
        compression_ratio=compression_ratio,
        tool_executions=tool_executions_json,
    )

    logger.info(
        f"Snapshot created: {len(messages)} msgs → {compressed_size} chars "
        f"({compression_ratio*100:.1f}% of original), "
        f"{len(key_quotes)} quotes, {len(keywords)} keywords"
    )

    return snapshot


def extract_key_quotes(
    messages: List[Dict[str, Any]],
    max_quotes: int = 5,
) -> List[str]:
    """Extract key quotes from conversation.

    Criteria for "key quotes":
    - Questions from user
    - Definitive statements
    - Decisions/confirmations
    - Technical details (numbers, dates, paths)

    Args:
        messages: Message list
        max_quotes: Maximum quotes to extract

    Returns:
        List of key quote strings
    """
    quotes = []

    for msg in messages:
        content = msg.get("content", "")
        role = msg.get("role", "unknown")

        # Skip very short messages
        if len(content) < 20:
            continue

        # User questions
        if role == "user" and "?" in content:
            # Take first sentence with question mark
            match = re.search(r'[^.!?]*\?', content)
            if match:
                quotes.append(f"{role}: {match.group().strip()}")

        # Assistant definitive statements
        elif role == "assistant":
            # Look for sentences with keywords
            if any(kw in content.lower() for kw in [
                "significa", "es decir", "en resumen", "por ejemplo",
                "importante", "clave", "crítico", "significa que"
            ]):
                # Take first significant sentence
                sentences = re.split(r'[.!?]', content)
                for sent in sentences:
                    if len(sent.strip()) > 30:
                        quotes.append(f"{role}: {sent.strip()}")
                        break

        # Technical details (paths, numbers, dates)
        if re.search(r'(/[^\s]+|[0-9]{2,}|[0-9]{4}-[0-9]{2}-[0-9]{2})', content):
            # Extract sentence with technical detail
            sentences = re.split(r'[.!?]', content)
            for sent in sentences:
                if re.search(r'(/[^\s]+|[0-9]{2,})', sent):
                    quotes.append(f"{role}: {sent.strip()}")
                    break

        if len(quotes) >= max_quotes:
            break

    return quotes[:max_quotes]


def extract_keywords(
    messages: List[Dict[str, Any]],
    max_keywords: int = 20,
) -> List[str]:
    """Extract keywords for BM25 search.

    Strategy:
    - Technical terms (camelCase, snake_case, file extensions)
    - Domain-specific nouns
    - Action verbs
    - Entities (capitalized words)

    Args:
        messages: Message list
        max_keywords: Maximum keywords to extract

    Returns:
        List of keyword strings
    """
    keyword_candidates = {}

    # Stopwords (Spanish + English common words)
    stopwords = {
        "el", "la", "de", "que", "en", "un", "una", "por", "para",
        "con", "es", "se", "al", "lo", "del", "las", "los", "su",
        "the", "a", "is", "in", "to", "of", "and", "for", "on",
        "i", "you", "it", "this", "that", "are", "as", "with", "be"
    }

    for msg in messages:
        content = msg.get("content", "")
        words = content.split()

        for word in words:
            # Clean word
            word_clean = re.sub(r'[^\w\-\.\/]', '', word).lower()

            if len(word_clean) < 3:
                continue

            if word_clean in stopwords:
                continue

            # Priority 1: Technical patterns
            if re.match(r'[a-z]+[A-Z]', word):  # camelCase
                keyword_candidates[word_clean] = keyword_candidates.get(word_clean, 0) + 3

            elif '_' in word_clean:  # snake_case
                keyword_candidates[word_clean] = keyword_candidates.get(word_clean, 0) + 3

            elif re.match(r'\w+\.(pdf|xlsx|docx|txt|py|js|json)', word_clean):  # file extensions
                keyword_candidates[word_clean] = keyword_candidates.get(word_clean, 0) + 4

            elif word_clean.startswith('/'):  # paths
                keyword_candidates[word_clean] = keyword_candidates.get(word_clean, 0) + 3

            # Priority 2: Entities (capitalized)
            elif word[0].isupper() and len(word) > 3:
                keyword_candidates[word_clean] = keyword_candidates.get(word_clean, 0) + 2

            # Priority 3: Longer words (likely domain-specific)
            elif len(word_clean) > 6:
                keyword_candidates[word_clean] = keyword_candidates.get(word_clean, 0) + 1

    # Sort by frequency and take top N
    sorted_keywords = sorted(
        keyword_candidates.items(),
        key=lambda x: x[1],
        reverse=True
    )

    keywords = [kw for kw, _ in sorted_keywords[:max_keywords]]

    logger.debug(f"Extracted {len(keywords)} keywords from conversation")

    return keywords


def should_create_snapshot(state: ConversationState) -> bool:
    """Determine if a snapshot should be created.

    Criteria:
    - Conversation has at least 10 messages
    - No snapshot created recently for this thread

    Args:
        state: Current conversation state

    Returns:
        True if snapshot should be created
    """
    messages = state.get("messages", [])

    if len(messages) < 10:
        return False

    # Check if last snapshot was recent (avoid duplicates)
    last_snapshot_time = state.get("last_snapshot_time")
    if last_snapshot_time:
        try:
            last_snapshot_dt = datetime.fromisoformat(
                last_snapshot_time.replace("Z", "+00:00")
            )
            now = datetime.utcnow()
            minutes_since = (now - last_snapshot_dt).total_seconds() / 60

            # Don't snapshot if last one was < 30 minutes ago
            if minutes_since < 30:
                return False
        except Exception:
            pass

    return True
