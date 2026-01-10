"""Context builder for assembling hierarchical LLM context."""
import logging
from typing import Optional

from src.memory.core.state import ConversationState
from src.memory.layers.short_term import ShortTermMemory
from src.memory.layers.tool_memory import ToolMemoryManager

logger = logging.getLogger(__name__)


class ContextBuilder:
    """Builds hierarchical context for LLM from conversation state.

    Assembles context in order:
    1. System prompt
    2. Pareto summary (compressed history)
    3. Recent messages (sliding window)
    4. Tool memory (documents/tools used)
    5. RAG context (retrieved documents)
    6. Current question
    """

    DEFAULT_SYSTEM_PROMPT = """You are a RAG (Retrieval-Augmented Generation) assistant specialized in analyzing documents and providing accurate answers based on retrieved information.

Capabilities:
- Analyze PDF, Word, Excel, PowerPoint documents
- Extract text from images (OCR)
- Extract and analyze compressed archives
- Search information in knowledge bases
- Remember prior conversations and tools used

Rules:
- Always cite sources when providing information
- If you do not have enough information, say so clearly
- Keep responses concise and relevant
- Remember the conversation context"""

    def __init__(
        self,
        system_prompt: Optional[str] = None,
        window_size: int = 10
    ):
        """Initialize context builder.

        Args:
            system_prompt: Optional custom system prompt
            window_size: Size of recent message window
        """
        self.system_prompt = system_prompt or self.DEFAULT_SYSTEM_PROMPT
        self.short_term = ShortTermMemory(window_size=window_size)
        self.tool_memory = ToolMemoryManager()

        logger.info(f"ContextBuilder initialized: window_size={window_size}")

    def build_context(
        self,
        state: ConversationState,
        current_question: str,
        rag_results: Optional[list[dict]] = None,
        include_system: bool = True
    ) -> str:
        """Build complete hierarchical context.

        Args:
            state: Current conversation state
            current_question: User's current question
            rag_results: Optional RAG retrieval results
            include_system: Include system prompt (default: True)

        Returns:
            Complete context string for LLM
        """
        sections = []

        # 1. System prompt
        if include_system:
            sections.append(f"# System\n{self.system_prompt}")

        # 2. Pareto summary (compressed history)
        pareto_summary = state.get("pareto_summary")
        if pareto_summary:
            sections.append(f"# Previous conversation summary\n{pareto_summary}")

        # 3. Recent messages (sliding window)
        recent = self.short_term.format_recent_messages(state)
        if recent:
            sections.append(f"# Recent messages\n{recent}")

        # 4. Tool memory (documents/tools used)
        tool_context = self.tool_memory.format_tool_memory(state, n=5)
        if tool_context:
            sections.append(f"# {tool_context}")

        # 5. Current context (if set)
        current_context = state.get("current_context")
        if current_context:
            sections.append(f"# Current state\n{current_context}")

        # 6. RAG context (retrieved documents)
        if rag_results:
            rag_context = self._format_rag_results(rag_results)
            if rag_context:
                sections.append(f"# Relevant documents\n{rag_context}")

        # 7. Current question
        sections.append(f"# Current question\n{current_question}")

        # Assemble
        full_context = "\n\n".join(sections)

        logger.debug(
            f"Built context: {len(full_context)} chars, "
            f"{len(sections)} sections"
        )

        return full_context

    def _format_rag_results(self, rag_results: list[dict]) -> str:
        """Format RAG retrieval results for context.

        Args:
            rag_results: List of retrieved document chunks

        Returns:
            Formatted string
        """
        if not rag_results:
            return ""

        lines = []
        for i, result in enumerate(rag_results, 1):
            content = result.get("content", result.get("text", ""))
            metadata = result.get("metadata", {})

            # Extract source info
            source = metadata.get("path", metadata.get("source", "unknown"))
            page = metadata.get("page", "")
            score = result.get("relevance_score", result.get("score", 0))

            # Format
            source_info = f"[Source: {source}"
            if page:
                source_info += f", page {page}"
            source_info += f", relevance: {score:.3f}]"

            lines.append(f"## Excerpt {i}\n{source_info}\n{content}")

        return "\n\n".join(lines)

    def estimate_tokens(self, text: str) -> int:
        """Rough token estimation.

        Args:
            text: Text to estimate

        Returns:
            Estimated token count (1 token ~= 4 chars)
        """
        return len(text) // 4

    def build_context_with_budget(
        self,
        state: ConversationState,
        current_question: str,
        rag_results: Optional[list[dict]] = None,
        max_tokens: int = 4000
    ) -> str:
        """Build context within token budget.

        Prioritizes:
        1. System prompt (fixed)
        2. Current question (fixed)
        3. Tool memory (important)
        4. Recent messages (trimmed if needed)
        5. RAG results (trimmed if needed)
        6. Pareto summary (trimmed if needed)

        Args:
            state: Current conversation state
            current_question: User's current question
            rag_results: Optional RAG results
            max_tokens: Maximum token budget

        Returns:
            Context string within budget
        """
        max_chars = max_tokens * 4
        sections = []
        used_chars = 0

        # System prompt (always include)
        system_section = f"# System\n{self.system_prompt}"
        sections.append(system_section)
        used_chars += len(system_section)

        # Current question (always include)
        question_section = f"# Current question\n{current_question}"
        sections.append(question_section)
        used_chars += len(question_section)

        # Remaining budget
        remaining = max_chars - used_chars

        # Tool memory (high priority)
        tool_context = self.tool_memory.format_tool_memory(state, n=5)
        if tool_context and len(tool_context) < remaining * 0.2:
            sections.insert(1, f"# {tool_context}")
            used_chars += len(tool_context)
            remaining = max_chars - used_chars

        # Recent messages (allocate 40% of remaining)
        recent_budget = int(remaining * 0.4)
        recent = self.short_term.format_recent_messages(state)
        if recent:
            if len(recent) > recent_budget:
                recent = recent[-recent_budget:]
            sections.insert(1, f"# Recent messages\n{recent}")
            used_chars += len(recent)
            remaining = max_chars - used_chars

        # RAG results (allocate 40% of remaining)
        if rag_results and remaining > 0:
            rag_budget = int(remaining * 0.4)
            rag_context = self._format_rag_results(rag_results)
            if rag_context:
                if len(rag_context) > rag_budget:
                    rag_context = rag_context[:rag_budget] + "..."
                sections.insert(-1, f"# Relevant documents\n{rag_context}")
                used_chars += len(rag_context)
                remaining = max_chars - used_chars

        # Pareto summary (use remaining budget)
        if remaining > 100:
            pareto = state.get("pareto_summary")
            if pareto:
                if len(pareto) > remaining:
                    pareto = pareto[:remaining] + "..."
                sections.insert(1, f"# Previous summary\n{pareto}")

        full_context = "\n\n".join(sections)

        logger.info(
            f"Built context with budget: {len(full_context)} chars "
            f"(~{len(full_context)//4} tokens, budget: {max_tokens})"
        )

        return full_context


def create_context_builder(
    system_prompt: Optional[str] = None,
    window_size: Optional[int] = None
) -> ContextBuilder:
    """Factory function to create context builder.

    Args:
        system_prompt: Optional custom system prompt
        window_size: Optional window size override

    Returns:
        Configured ContextBuilder instance
    """
    import os

    if window_size is None:
        window_size = _config.MEMORY_WINDOW_SIZE

    return ContextBuilder(
        system_prompt=system_prompt,
        window_size=window_size
    )
