#!/usr/bin/env python3
"""Quick verification script for Memory System Phase 1.

Tests core components without requiring pytest or dependencies.
"""
import sys
import time

# Test identifiers
print("=" * 60)
print("Testing identifiers.py...")
print("=" * 60)

from src.workflows.memory.core.identifiers import (
    generate_user_id,
    generate_thread_id,
    validate_user_id,
    validate_thread_id,
)

# Test user_id generation
print("\n1. Testing user_id generation...")
user_id1 = generate_user_id(stable_seed="test-seed")
print(f"   Generated user_id: {user_id1[:16]}...")
assert len(user_id1) == 64, "user_id should be 64 chars"
assert validate_user_id(user_id1), "user_id should be valid"

user_id2 = generate_user_id(stable_seed="test-seed")
assert user_id1 == user_id2, "Same seed should produce same user_id"
print("   ✓ user_id generation works (deterministic with seed)")

# Test thread_id generation
print("\n2. Testing thread_id generation...")
thread_id1 = generate_thread_id(
    user_id=user_id1,
    server_secret="test-secret",
    conversation_seed="conv-1"
)
print(f"   Generated thread_id: {thread_id1[:16]}...")
assert len(thread_id1) == 64, "thread_id should be 64 chars"
assert validate_thread_id(thread_id1), "thread_id should be valid"

thread_id2 = generate_thread_id(
    user_id=user_id1,
    server_secret="test-secret",
    conversation_seed="conv-1"
)
assert thread_id1 == thread_id2, "Same inputs should produce same thread_id"
print("   ✓ thread_id generation works (deterministic with seed)")

# Test different conversations
thread_id3 = generate_thread_id(
    user_id=user_id1,
    server_secret="test-secret",
    conversation_seed="conv-2"
)
assert thread_id1 != thread_id3, "Different seeds should produce different thread_ids"
print("   ✓ Different conversation seeds produce different thread_ids")

# Test state
print("\n" + "=" * 60)
print("Testing state.py...")
print("=" * 60)

from src.workflows.memory.core.state import (
    create_initial_state,
    update_state_metadata,
    add_tool_execution,
    get_recent_tool_executions,
    find_tool_execution_by_id,
    ToolExecution,
)

print("\n3. Testing state creation...")
state = create_initial_state(
    user_id=user_id1,
    thread_id=thread_id1
)
print(f"   Created state for thread: {state['thread_id'][:16]}...")
assert state["user_id"] == user_id1
assert state["thread_id"] == thread_id1
assert state["message_count"] == 0
assert len(state["tool_executions"]) == 0
print("   ✓ Initial state created correctly")

print("\n4. Testing tool execution tracking...")
execution1: ToolExecution = {
    "tool": "office",
    "doc_id": "doc#1",
    "file_path": "/path/to/document.docx",
    "file_hash": "abc123",
    "summary": "Q3 Financial Report",
    "structure": "12 pages",
    "timestamp": time.time(),
    "output_path": "/tmp/artifacts/doc1.pdf"
}

state = add_tool_execution(state, execution1)
print(f"   Added tool execution: {execution1['doc_id']}")
assert len(state["tool_executions"]) == 1
print("   ✓ Tool execution added to state")

print("\n5. Testing tool execution retrieval...")
found = find_tool_execution_by_id(state, "doc#1")
assert found is not None
assert found["summary"] == "Q3 Financial Report"
print(f"   Found execution: {found['doc_id']} - {found['summary']}")
print("   ✓ Tool execution retrieval works")

# Add more executions
print("\n6. Testing multiple tool executions...")
for i in range(2, 6):
    execution: ToolExecution = {
        "tool": "ocr" if i % 2 == 0 else "archive",
        "doc_id": f"doc#{i}",
        "file_path": f"/path/file{i}",
        "file_hash": f"hash{i}",
        "summary": f"Document {i}",
        "structure": f"{i} pages",
        "timestamp": time.time() + i
    }
    state = add_tool_execution(state, execution)

assert len(state["tool_executions"]) == 5
print(f"   Added {len(state['tool_executions'])} total executions")

recent = get_recent_tool_executions(state, n=3)
assert len(recent) == 3
print(f"   Retrieved {len(recent)} most recent executions:")
for exec in recent:
    print(f"      - {exec['doc_id']}: {exec['summary']}")
print("   ✓ Recent executions retrieved correctly")

# Test metadata updates
print("\n7. Testing metadata updates...")
original_time = state["last_updated"]
time.sleep(0.01)
state = update_state_metadata(state)
assert state["last_updated"] > original_time
print("   ✓ State metadata updates correctly")

# Summary
print("\n" + "=" * 60)
print("✓ ALL PHASE 1 TESTS PASSED!")
print("=" * 60)
print("\nPhase 1 Components Verified:")
print("  ✓ identifiers.py - User/Thread ID generation")
print("  ✓ state.py - Conversation state management")
print("\nNext Steps:")
print("  1. Install dependencies: pip install -r requirements.txt")
print("  2. Ensure SQLite control plane is available (data/control_plane.db)")
print("  3. Test checkpointer.py with the SQLite control plane (context checkpoint compaction)")
print("  4. Continue to Phase 2 (Compression + Tool Memory)")
print()

sys.exit(0)
