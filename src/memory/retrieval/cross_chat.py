"""Cross-chat retrieval: Search across past conversations.

Implements Fase 5 del Plan Maestro:
- Search ChatMemory snapshots by semantic similarity
- Combine with KB retrieval
- RRF fusion for ranking
"""
import logging
from typing import List, Dict, Any, Optional

from src.memory.storage.chat_memory_persistence import ChatMemoryPersistence

logger = logging.getLogger(__name__)


class CrossChatRetriever:
    """Retrieves relevant information from past conversations."""

    def __init__(
        self,
        chat_memory: ChatMemoryPersistence,
        top_k: int = 3,
    ):
        """Initialize cross-chat retriever.

        Args:
            chat_memory: ChatMemory persistence layer
            top_k: Number of past conversations to retrieve
        """
        self.chat_memory = chat_memory
        self.top_k = top_k

    def retrieve(
        self,
        query: str,
        user_id: str,
        top_k: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve relevant past conversation snapshots.

        Args:
            query: User's current query
            user_id: User identifier
            top_k: Override default top_k

        Returns:
            List of relevant snapshot summaries with metadata
        """
        k = top_k or self.top_k

        try:
            # Search ChatMemory for relevant past conversations
            snapshots = self.chat_memory.search_snapshots(
                query=query,
                user_id=user_id,
                top_k=k,
                alpha=0.7,  # Balanced hybrid search
            )

            # Format for context injection
            results = []
            for snapshot in snapshots:
                result = {
                    "type": "chat_memory",
                    "summary": snapshot.get("summary_dense", ""),
                    "key_quotes": snapshot.get("key_quotes", []),
                    "keywords": snapshot.get("keywords", []),
                    "thread_id": snapshot.get("thread_id", ""),
                    "timestamp": snapshot.get("timestamp", ""),
                    "score": snapshot.get("score", 0.0),
                    "message_count": snapshot.get("original_message_count", 0),
                }
                results.append(result)

            logger.info(
                f"Cross-chat retrieval: found {len(results)} relevant past conversations"
            )
            return results

        except Exception as e:
            logger.error(f"Cross-chat retrieval failed: {e}", exc_info=True)
            return []

    def format_for_context(
        self,
        snapshots: List[Dict[str, Any]],
        max_length: int = 1000,
    ) -> str:
        """Format snapshots for LLM context injection.

        Args:
            snapshots: List of snapshot results
            max_length: Maximum character length

        Returns:
            Formatted context string
        """
        if not snapshots:
            return ""

        lines = ["## Conversaciones relevantes del pasado:"]
        current_length = len(lines[0])

        for i, snapshot in enumerate(snapshots, 1):
            # Format snapshot header
            timestamp = snapshot.get("timestamp", "")[:10]  # YYYY-MM-DD
            msg_count = snapshot.get("message_count", 0)
            header = f"\n### Conversation {i} ({timestamp}, {msg_count} messages):"

            # Add summary
            summary = snapshot.get("summary", "")
            if len(summary) > 300:
                summary = summary[:297] + "..."

            # Add key quotes if available
            quotes = snapshot.get("key_quotes", [])
            quotes_text = ""
            if quotes:
                quotes_text = "\n**Citas clave:**\n" + "\n".join(
                    f"- {quote}" for quote in quotes[:3]
                )

            # Combine
            section = f"{header}\n{summary}{quotes_text}\n"

            # Check length budget
            if current_length + len(section) > max_length:
                break

            lines.append(section)
            current_length += len(section)

        return "\n".join(lines)


def create_cross_chat_retriever(
    chat_memory: ChatMemoryPersistence,
    top_k: int = 3,
) -> CrossChatRetriever:
    """Factory function to create cross-chat retriever.

    Args:
        chat_memory: ChatMemory persistence layer
        top_k: Number of past conversations to retrieve

    Returns:
        CrossChatRetriever instance
    """
    return CrossChatRetriever(chat_memory, top_k)
