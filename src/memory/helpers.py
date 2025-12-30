"""Helper functions for memory system integration."""
import logging
import os
from typing import Optional

from src.memory.core.state import (
    ConversationState,
    create_initial_state,
    update_state_metadata,
)
from src.memory.core.checkpointer import create_checkpointer
from src.memory.compression.pareto import compress_conversation
from src.memory.compression.summarizer import create_summarizer
from src.memory.layers.short_term import create_short_term_memory
from src.memory.context.builder import create_context_builder

logger = logging.getLogger(__name__)


# Global checkpointer instance
_checkpointer = None


def get_checkpointer():
    """Get or create global checkpointer instance.

    Returns:
        TTLRedisSaver instance
    """
    global _checkpointer

    if _checkpointer is None:
        redis_host = os.getenv("REDIS_HOST", "127.0.0.1")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))
        redis_password = (os.getenv("REDIS_PASSWORD") or "").strip() or None
        ttl_seconds = int(os.getenv("MEMORY_TTL", "172800"))

        _checkpointer = create_checkpointer(
            redis_host=redis_host,
            redis_port=redis_port,
            redis_password=redis_password,
            ttl_seconds=ttl_seconds
        )
        logger.info("Checkpointer initialized")

    return _checkpointer


def load_or_create_state(
    user_id: str,
    thread_id: str
) -> ConversationState:
    """Load existing state or create new one.

    Args:
        user_id: User identifier
        thread_id: Thread identifier

    Returns:
        Conversation state (existing or new)
    """
    checkpointer = get_checkpointer()
    config = {"configurable": {"thread_id": thread_id}}

    try:
        # Try to load existing state
        checkpoint = checkpointer.get(config)

        if checkpoint and "channel_values" in checkpoint:
            state = checkpoint["channel_values"]
            logger.info(f"Loaded existing state for thread {thread_id[:8]}...")
            return state
    except Exception as e:
        logger.warning(f"Could not load state: {e}")

    # Create new state
    logger.info(f"Creating new state for thread {thread_id[:8]}...")
    return create_initial_state(user_id, thread_id)


def save_state(
    state: ConversationState,
    thread_id: str
) -> None:
    """Save state to Redis with TTL.

    Args:
        state: Conversation state to save
        thread_id: Thread identifier
    """
    checkpointer = get_checkpointer()
    config = {"configurable": {"thread_id": thread_id}}

    # Update metadata
    state = update_state_metadata(state)

    # Create checkpoint structure
    checkpoint = {
        "channel_values": state,
        "v": 1
    }

    metadata = {
        "source": "memory_system",
        "step": state.get("message_count", 0)
    }

    try:
        checkpointer.put(config, checkpoint, metadata)
        logger.debug(f"Saved state for thread {thread_id[:8]}...")
    except Exception as e:
        logger.error(f"Failed to save state: {e}", exc_info=True)


def should_compress_state(state: ConversationState) -> bool:
    """Check if state should be compressed.

    Args:
        state: Current conversation state

    Returns:
        True if compression recommended
    """
    window_size = int(os.getenv("MEMORY_WINDOW_SIZE", "10"))
    messages = state.get("messages", [])

    # Compress if we have more than 2x window size
    return len(messages) > window_size * 2


def compress_and_update_state(state: ConversationState) -> ConversationState:
    """Compress state using Pareto + LLM.

    Args:
        state: Current conversation state

    Returns:
        Updated state with compression applied
    """
    messages = state.get("messages", [])

    if not messages:
        return state

    logger.info(f"Compressing {len(messages)} messages...")

    # Try LLM compression first
    try:
        summarizer = create_summarizer()
        summary = summarizer.summarize_messages(messages)
        state["pareto_summary"] = summary
        logger.info("LLM compression successful")
    except Exception as e:
        logger.warning(f"LLM compression failed: {e}, using Pareto")
        # Fallback to algorithmic compression
        summary = compress_conversation(messages, max_tokens=500)
        state["pareto_summary"] = summary

    # Update recent messages window
    short_term = create_short_term_memory()
    state = short_term.update_window(state)

    logger.info(f"Compression complete: summary={len(summary)} chars")

    return state


def build_llm_context(
    state: ConversationState,
    question: str,
    rag_results: Optional[list[dict]] = None
) -> str:
    """Build complete LLM context from state.

    Args:
        state: Current conversation state
        question: Current user question
        rag_results: Optional RAG retrieval results

    Returns:
        Complete context string for LLM
    """
    builder = create_context_builder()

    context = builder.build_context(
        state=state,
        current_question=question,
        rag_results=rag_results
    )

    return context
