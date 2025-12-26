"""Short-term memory layer managing recent message window."""
import logging
from typing import Optional

from src.memory.core.state import ConversationState

logger = logging.getLogger(__name__)


class ShortTermMemory:
    """Manages sliding window of recent messages.

    Keeps the most recent N messages in full detail for immediate context.
    """

    def __init__(self, window_size: int = 10):
        """Initialize short-term memory.

        Args:
            window_size: Number of recent messages to keep (default: 10)
        """
        self.window_size = window_size
        logger.info(f"ShortTermMemory initialized: window_size={window_size}")

    def update_window(self, state: ConversationState) -> ConversationState:
        """Update recent messages window in state.

        Keeps only the most recent window_size messages.

        Args:
            state: Current conversation state

        Returns:
            Updated state with refreshed recent_messages
        """
        all_messages = state.get("messages", [])

        if len(all_messages) <= self.window_size:
            # All messages fit in window
            state["recent_messages"] = all_messages.copy()
        else:
            # Keep only most recent
            state["recent_messages"] = all_messages[-self.window_size:]

        logger.debug(
            f"Updated window: {len(state['recent_messages'])} messages "
            f"(total: {len(all_messages)})"
        )

        return state

    def get_recent_messages(self, state: ConversationState) -> list[dict]:
        """Get recent messages from state.

        Args:
            state: Current conversation state

        Returns:
            List of recent messages
        """
        return state.get("recent_messages", [])

    def format_recent_messages(
        self,
        state: ConversationState,
        include_system: bool = False
    ) -> str:
        """Format recent messages for context injection.

        Args:
            state: Current conversation state
            include_system: Whether to include system messages (default: False)

        Returns:
            Formatted string of recent messages
        """
        recent = self.get_recent_messages(state)

        if not recent:
            return ""

        lines = []
        for msg in recent:
            role = msg.get("role", "unknown")

            # Skip system messages unless requested
            if role == "system" and not include_system:
                continue

            content = msg.get("content", "")
            lines.append(f"{role}: {content}")

        return "\n".join(lines)

    def should_compress(self, state: ConversationState) -> bool:
        """Check if conversation should be compressed.

        Returns True if total messages exceed window size significantly.

        Args:
            state: Current conversation state

        Returns:
            True if compression recommended
        """
        all_messages = state.get("messages", [])
        # Compress if we have more than 2x window size
        threshold = self.window_size * 2
        return len(all_messages) > threshold


def create_short_term_memory(window_size: Optional[int] = None) -> ShortTermMemory:
    """Factory function to create short-term memory.

    Args:
        window_size: Optional window size override

    Returns:
        Configured ShortTermMemory instance
    """
    import os

    if window_size is None:
        window_size = int(os.getenv("MEMORY_WINDOW_SIZE", "10"))

    return ShortTermMemory(window_size=window_size)