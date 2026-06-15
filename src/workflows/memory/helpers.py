"""Helper functions for memory system integration."""
import logging
import os
from typing import Optional

from src.workflows.memory.core.state import (
    ConversationState,
    create_initial_state,
    update_state_metadata,
)
from src.workflows.memory.core.checkpointer import create_checkpointer
from src.workflows.memory.compression.pareto import compress_conversation
from src.workflows.memory.compression.summarizer import create_summarizer
from src.workflows.memory.layers.short_term import create_short_term_memory
from src.workflows.memory.context.builder import create_context_builder
import src.settings as settings

logger = logging.getLogger(__name__)


# Global checkpointer instance
_checkpointer = None


def get_checkpointer():
    """Get or create global checkpointer instance.

    Returns:
        SQLiteCheckpointer instance
    """
    global _checkpointer

    if _checkpointer is None:
        _checkpointer = create_checkpointer(
            ttl_seconds=settings.MEMORY_TTL
        )
        logger.info("Checkpointer initialized")

    return _checkpointer


def _build_checkpoint_config(thread_id: str) -> dict:
    """Build LangGraph checkpoint config with a stable namespace."""
    return {"configurable": {"thread_id": thread_id, "checkpoint_ns": settings.CHECKPOINT_NS}}


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
    config = _build_checkpoint_config(thread_id)

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
    """Save state to the control plane with TTL.

    Args:
        state: Conversation state to save
        thread_id: Thread identifier
    """
    checkpointer = get_checkpointer()
    config = _build_checkpoint_config(thread_id)

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


def _estimate_state_size_bytes(state: ConversationState) -> int:
    """Estimate size of state in bytes.

    Args:
        state: Current conversation state

    Returns:
        Estimated size in bytes
    """
    import sys
    import json

    try:
        # Serialize state to JSON to get accurate size estimate
        state_json = json.dumps(dict(state))
        return sys.getsizeof(state_json)
    except Exception as e:
        logger.warning(f"Failed to estimate state size: {e}")
        # Fallback: rough estimate based on message count
        messages = state.get("messages", [])
        # Assume ~500 bytes per message on average
        return len(messages) * 500


def should_compress_state(state: ConversationState) -> bool:
    """Check if state should be compressed.

    Compression is triggered when:
    1. State size approaches memory limit (configurable)
    2. Message count exceeds 2x window size

    Args:
        state: Current conversation state

    Returns:
        True if compression recommended
    """
    window_size = settings.MEMORY_WINDOW_SIZE
    max_state_size_kb = settings.MAX_STATE_SIZE_KB
    compression_threshold = settings.COMPRESSION_THRESHOLD

    messages = state.get("messages", [])

    # Check 1: Message count threshold (existing behavior)
    message_count_exceeded = len(messages) > window_size * 2

    # Check 2: Memory size threshold (new behavior)
    state_size_bytes = _estimate_state_size_bytes(state)
    state_size_kb = state_size_bytes / 1024
    max_size_kb = max_state_size_kb
    size_threshold_exceeded = state_size_kb >= (max_size_kb * compression_threshold)

    # Log compression trigger details
    if message_count_exceeded or size_threshold_exceeded:
        logger.info(
            f"Compression check: messages={len(messages)}/{window_size * 2}, "
            f"size={state_size_kb:.1f}KB/{max_size_kb * compression_threshold:.1f}KB "
            f"(limit={max_size_kb}KB)"
        )

    # Trigger compression if either threshold exceeded
    return message_count_exceeded or size_threshold_exceeded


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
