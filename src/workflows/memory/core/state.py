"""Conversation state definition for memory system.

Defines the complete state structure for conversations, including:
- Message history
- Compressed summaries (Pareto)
- Tool execution memory
- Current context tracking
"""
from typing import Annotated, Optional
from typing_extensions import TypedDict

from langgraph.graph import MessagesState
from langgraph.graph.message import add_messages


class ToolExecution(TypedDict, total=False):
    """Record of a single tool execution.

    Attributes:
        tool: Tool name (office, ocr, archive)
        doc_id: Logical identifier (doc#1, doc#2, etc.)
        file_path: Original file path
        file_hash: SHA-256 hash of input file
        summary: Ultra-compact summary of document
        structure: Structural metadata (pages, sheets, folders)
        timestamp: Unix timestamp of execution
        output_path: Path to generated artifact
        metadata: Additional tool-specific metadata
    """
    tool: str  # "office" | "ocr" | "archive"
    doc_id: str  # "doc#1", "doc#2", etc.
    file_path: str
    file_hash: str
    summary: str  # Ultra-compact (1-2 sentences)
    structure: str  # "12 pages" | "3 sheets" | "15 files"
    timestamp: float
    output_path: Optional[str]
    metadata: Optional[dict]


class ConversationState(MessagesState):
    """Complete state for a conversation thread.

    Extends MessagesState (LangChain message list) with additional
    memory layers:
    - Short-term: Recent message window
    - Pareto: Compressed conversation summary
    - Tool memory: References to tools used
    - Context: Current conversation state

    This is the core data structure that gets persisted to Redis
    and loaded on each request.

    Example:
        >>> state = ConversationState(
        ...     user_id="abc123...",
        ...     thread_id="def456...",
        ...     messages=[],
        ...     recent_messages=[],
        ...     pareto_summary=None,
        ...     tool_executions=[],
        ...     current_context=None,
        ...     created_at=time.time(),
        ...     last_updated=time.time(),
        ...     message_count=0
        ... )
    """

    # Identifiers
    user_id: str
    thread_id: str

    # Messages (inherited from MessagesState)
    # messages: Annotated[list, add_messages]

    # Short-term memory (recent window)
    recent_messages: list[dict]

    # Pareto compression (80/20 summary of history)
    pareto_summary: Optional[str]

    # Tool memory (references to tools used in conversation)
    tool_executions: list[ToolExecution]

    # Current context ("Analyzing document X...")
    current_context: Optional[str]

    # Metadata
    created_at: float  # Unix timestamp
    last_updated: float  # Unix timestamp
    message_count: int


def create_initial_state(
    user_id: str,
    thread_id: str,
    created_at: Optional[float] = None
) -> ConversationState:
    """Create initial conversation state.

    Args:
        user_id: User identifier
        thread_id: Thread identifier
        created_at: Optional creation timestamp (defaults to now)

    Returns:
        Fresh ConversationState with empty history

    Example:
        >>> import time
        >>> state = create_initial_state(
        ...     user_id="abc123...",
        ...     thread_id="def456..."
        ... )
        >>> state["message_count"]
        0
    """
    import time

    if created_at is None:
        created_at = time.time()

    return ConversationState(
        user_id=user_id,
        thread_id=thread_id,
        messages=[],
        recent_messages=[],
        pareto_summary=None,
        tool_executions=[],
        current_context=None,
        created_at=created_at,
        last_updated=created_at,
        message_count=0
    )


def update_state_metadata(state: ConversationState) -> ConversationState:
    """Update state metadata (last_updated, message_count).

    Args:
        state: Current conversation state

    Returns:
        Updated state with refreshed metadata

    Example:
        >>> state = create_initial_state("user1", "thread1")
        >>> # ... add messages ...
        >>> state = update_state_metadata(state)
    """
    import time

    state["last_updated"] = time.time()
    state["message_count"] = len(state.get("messages", []))

    return state


def add_tool_execution(
    state: ConversationState,
    tool_execution: ToolExecution
) -> ConversationState:
    """Add tool execution record to state.

    Args:
        state: Current conversation state
        tool_execution: Tool execution record to add

    Returns:
        Updated state with new tool execution

    Example:
        >>> execution = ToolExecution(
        ...     tool="office",
        ...     doc_id="doc#1",
        ...     file_path="/path/to/file.docx",
        ...     file_hash="abc123...",
        ...     summary="Q3 financial report",
        ...     structure="12 pages",
        ...     timestamp=time.time(),
        ...     output_path="/tmp/artifacts/thread-xxx/doc1.pdf"
        ... )
        >>> state = add_tool_execution(state, execution)
    """
    state["tool_executions"].append(tool_execution)
    state = update_state_metadata(state)
    return state


def get_recent_tool_executions(
    state: ConversationState,
    n: int = 5
) -> list[ToolExecution]:
    """Get N most recent tool executions.

    Args:
        state: Current conversation state
        n: Number of executions to return

    Returns:
        List of recent tool executions (newest first)

    Example:
        >>> recent = get_recent_tool_executions(state, n=3)
        >>> for exec in recent:
        ...     print(f"{exec['doc_id']}: {exec['summary']}")
    """
    executions = state.get("tool_executions", [])
    # Sort by timestamp descending (newest first)
    sorted_execs = sorted(executions, key=lambda x: x["timestamp"], reverse=True)
    return sorted_execs[:n]


def find_tool_execution_by_id(
    state: ConversationState,
    doc_id: str
) -> Optional[ToolExecution]:
    """Find tool execution by document ID.

    Args:
        state: Current conversation state
        doc_id: Document ID to search for (e.g., "doc#1")

    Returns:
        Tool execution record or None if not found

    Example:
        >>> execution = find_tool_execution_by_id(state, "doc#1")
        >>> if execution:
        ...     print(execution["summary"])
    """
    executions = state.get("tool_executions", [])
    for execution in executions:
        if execution["doc_id"] == doc_id:
            return execution
    return None
