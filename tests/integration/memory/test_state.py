"""Tests for conversation state management."""
import time

import pytest

from src.workflows.memory.core.state import (
    ConversationState,
    ToolExecution,
    create_initial_state,
    update_state_metadata,
    add_tool_execution,
    get_recent_tool_executions,
    find_tool_execution_by_id,
)


class TestCreateInitialState:
    """Tests for create_initial_state()."""

    def test_creates_empty_state(self):
        """Should create state with empty history."""
        state = create_initial_state(
            user_id="user123",
            thread_id="thread456"
        )

        assert state["user_id"] == "user123"
        assert state["thread_id"] == "thread456"
        assert state["messages"] == []
        assert state["recent_messages"] == []
        assert state["pareto_summary"] is None
        assert state["tool_executions"] == []
        assert state["current_context"] is None
        assert state["message_count"] == 0

    def test_sets_timestamps(self):
        """Should set created_at and last_updated."""
        before = time.time()
        state = create_initial_state("user1", "thread1")
        after = time.time()

        assert before <= state["created_at"] <= after
        assert before <= state["last_updated"] <= after
        assert state["created_at"] == state["last_updated"]

    def test_custom_timestamp(self):
        """Should accept custom creation timestamp."""
        custom_time = 1234567890.0
        state = create_initial_state(
            "user1",
            "thread1",
            created_at=custom_time
        )

        assert state["created_at"] == custom_time
        assert state["last_updated"] == custom_time


class TestUpdateStateMetadata:
    """Tests for update_state_metadata()."""

    def test_updates_timestamp(self):
        """Should update last_updated timestamp."""
        state = create_initial_state("user1", "thread1")
        original_time = state["last_updated"]

        time.sleep(0.01)  # Small delay
        state = update_state_metadata(state)

        assert state["last_updated"] > original_time

    def test_updates_message_count(self):
        """Should update message count based on messages."""
        state = create_initial_state("user1", "thread1")

        # Add some messages
        state["messages"] = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi"}
        ]

        state = update_state_metadata(state)
        assert state["message_count"] == 2


class TestAddToolExecution:
    """Tests for add_tool_execution()."""

    def test_adds_execution_to_state(self):
        """Should add tool execution to list."""
        state = create_initial_state("user1", "thread1")

        execution: ToolExecution = {
            "tool": "office",
            "doc_id": "doc#1",
            "file_path": "/path/to/file.docx",
            "file_hash": "abc123",
            "summary": "Test document",
            "structure": "5 pages",
            "timestamp": time.time(),
            "output_path": "/tmp/artifacts/doc1.pdf"
        }

        state = add_tool_execution(state, execution)

        assert len(state["tool_executions"]) == 1
        assert state["tool_executions"][0]["doc_id"] == "doc#1"

    def test_updates_metadata(self):
        """Should update state metadata when adding execution."""
        state = create_initial_state("user1", "thread1")
        original_time = state["last_updated"]

        time.sleep(0.01)

        execution: ToolExecution = {
            "tool": "ocr",
            "doc_id": "doc#1",
            "file_path": "/path/to/scan.pdf",
            "file_hash": "def456",
            "summary": "Scanned document",
            "structure": "10 pages",
            "timestamp": time.time()
        }

        state = add_tool_execution(state, execution)

        assert state["last_updated"] > original_time

    def test_multiple_executions(self):
        """Should handle multiple tool executions."""
        state = create_initial_state("user1", "thread1")

        for i in range(3):
            execution: ToolExecution = {
                "tool": "office",
                "doc_id": f"doc#{i+1}",
                "file_path": f"/path/file{i}.docx",
                "file_hash": f"hash{i}",
                "summary": f"Document {i}",
                "structure": f"{i+1} pages",
                "timestamp": time.time()
            }
            state = add_tool_execution(state, execution)

        assert len(state["tool_executions"]) == 3
        assert state["tool_executions"][0]["doc_id"] == "doc#1"
        assert state["tool_executions"][2]["doc_id"] == "doc#3"


class TestGetRecentToolExecutions:
    """Tests for get_recent_tool_executions()."""

    def test_returns_empty_for_no_executions(self):
        """Should return empty list if no executions."""
        state = create_initial_state("user1", "thread1")
        recent = get_recent_tool_executions(state, n=5)
        assert recent == []

    def test_returns_all_if_less_than_n(self):
        """Should return all executions if less than N."""
        state = create_initial_state("user1", "thread1")

        # Add 2 executions
        for i in range(2):
            execution: ToolExecution = {
                "tool": "office",
                "doc_id": f"doc#{i+1}",
                "file_path": f"/file{i}",
                "file_hash": f"hash{i}",
                "summary": f"Doc {i}",
                "structure": "1 page",
                "timestamp": time.time() + i
            }
            state = add_tool_execution(state, execution)

        recent = get_recent_tool_executions(state, n=5)
        assert len(recent) == 2

    def test_returns_n_most_recent(self):
        """Should return N most recent executions."""
        state = create_initial_state("user1", "thread1")

        # Add 10 executions with incrementing timestamps
        for i in range(10):
            execution: ToolExecution = {
                "tool": "office",
                "doc_id": f"doc#{i+1}",
                "file_path": f"/file{i}",
                "file_hash": f"hash{i}",
                "summary": f"Doc {i}",
                "structure": "1 page",
                "timestamp": time.time() + i
            }
            state = add_tool_execution(state, execution)

        recent = get_recent_tool_executions(state, n=3)

        assert len(recent) == 3
        # Should be newest first
        assert recent[0]["doc_id"] == "doc#10"
        assert recent[1]["doc_id"] == "doc#9"
        assert recent[2]["doc_id"] == "doc#8"


class TestFindToolExecutionByID:
    """Tests for find_tool_execution_by_id()."""

    def test_finds_existing_execution(self):
        """Should find execution by doc_id."""
        state = create_initial_state("user1", "thread1")

        execution: ToolExecution = {
            "tool": "office",
            "doc_id": "doc#1",
            "file_path": "/path/to/file.docx",
            "file_hash": "abc123",
            "summary": "Target document",
            "structure": "5 pages",
            "timestamp": time.time()
        }
        state = add_tool_execution(state, execution)

        found = find_tool_execution_by_id(state, "doc#1")

        assert found is not None
        assert found["doc_id"] == "doc#1"
        assert found["summary"] == "Target document"

    def test_returns_none_for_missing(self):
        """Should return None if execution not found."""
        state = create_initial_state("user1", "thread1")

        found = find_tool_execution_by_id(state, "doc#999")
        assert found is None

    def test_finds_among_multiple(self):
        """Should find correct execution among multiple."""
        state = create_initial_state("user1", "thread1")

        # Add multiple executions
        for i in range(5):
            execution: ToolExecution = {
                "tool": "office",
                "doc_id": f"doc#{i+1}",
                "file_path": f"/file{i}",
                "file_hash": f"hash{i}",
                "summary": f"Document {i}",
                "structure": "1 page",
                "timestamp": time.time()
            }
            state = add_tool_execution(state, execution)

        # Find middle one
        found = find_tool_execution_by_id(state, "doc#3")

        assert found is not None
        assert found["doc_id"] == "doc#3"
        assert found["summary"] == "Document 2"


class TestToolExecutionType:
    """Tests for ToolExecution TypedDict."""

    def test_creates_valid_execution(self):
        """Should create valid tool execution dict."""
        execution: ToolExecution = {
            "tool": "archive",
            "doc_id": "doc#1",
            "file_path": "/path/archive.zip",
            "file_hash": "hash123",
            "summary": "Extracted archive",
            "structure": "15 files",
            "timestamp": 1234567890.0,
            "output_path": "/tmp/extracted/",
            "metadata": {"size_mb": 10.5}
        }

        assert execution["tool"] == "archive"
        assert execution["doc_id"] == "doc#1"
        assert execution["metadata"]["size_mb"] == 10.5

    def test_optional_fields(self):
        """Should allow optional fields to be omitted."""
        execution: ToolExecution = {
            "tool": "ocr",
            "doc_id": "doc#2",
            "file_path": "/scan.pdf",
            "file_hash": "hash456",
            "summary": "OCR result",
            "structure": "3 pages",
            "timestamp": time.time()
            # output_path and metadata omitted
        }

        assert execution["tool"] == "ocr"
        assert "output_path" not in execution
        assert "metadata" not in execution
