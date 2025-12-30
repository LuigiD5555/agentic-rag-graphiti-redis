# Memory System

Hierarchical memory system for RAG with LangChain/LangGraph.

## Implementation Status

### Phase 1: Foundations (COMPLETED)

**Implemented components**:

- identifiers.py: Cryptographic generation of user_id and thread_id
- state.py: Conversation state definition (ConversationState)
- checkpointer.py: Redis checkpointer with smart TTL (48h + touch)
- Tests: Full suites in `tests/memory/`

**Created files**:

```
src/memory/
├── core/
│   ├── identifiers.py      ✅ User/Thread ID generation
│   ├── state.py            ✅ ConversationState definition
│   └── checkpointer.py     ✅ TTL Redis checkpointer
├── layers/                 (Phase 2)
├── compression/            (Phase 2)
├── artifacts/              (Phase 2)
└── context/                (Phase 3)
```

## Installation

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

Added dependencies:

```
langgraph
langgraph-checkpoint-redis
```

### 2. Verify installation

```bash
# Quick verification (no Redis)
python3 verify_memory_phase1.py

# Full tests (requires pytest and Redis)
pytest tests/memory/ -v
```

## Phase 1 Usage

### Identity Generation

```python
from src.memory.core.identifiers import (
    generate_user_id,
    generate_thread_id,
    validate_user_id,
    validate_thread_id,
)

# Generate user_id (stable SHA-256)
user_id = generate_user_id(
    client_info={"ip": "127.0.0.1", "ua": "Mozilla/5.0"}
)

# Generate thread_id (unique HMAC-SHA256)
thread_id = generate_thread_id(
    user_id=user_id,
    server_secret="your-secret-from-env"  # From THREAD_SECRET in .env
)

# Validate IDs
assert validate_user_id(user_id)
assert validate_thread_id(thread_id)
```

### State Management

```python
from src.memory.core.state import (
    create_initial_state,
    add_tool_execution,
    get_recent_tool_executions,
    find_tool_execution_by_id,
    ToolExecution,
)
import time

# Create initial state
state = create_initial_state(
    user_id=user_id,
    thread_id=thread_id
)

# Add tool execution
execution: ToolExecution = {
    "tool": "office",
    "doc_id": "doc#1",
    "file_path": "/path/to/document.docx",
    "file_hash": "abc123...",
    "summary": "Q3 Financial Report",
    "structure": "12 pages",
    "timestamp": time.time(),
    "output_path": "/tmp/artifacts/thread-xxx/doc1.pdf"
}

state = add_tool_execution(state, execution)

# Get recent executions
recent = get_recent_tool_executions(state, n=5)
for exec in recent:
    print(f"{exec['doc_id']}: {exec['summary']}")

# Find by ID
doc = find_tool_execution_by_id(state, "doc#1")
```

### Redis Persistence (Smart TTL)

```python
from src.memory.core.checkpointer import create_checkpointer

# Create checkpointer (requires Redis running)
checkpointer = create_checkpointer(
    redis_host="127.0.0.1",
    redis_port=6379,
    ttl_seconds=172800  # 48 hours
)

# Use with LangGraph
from langgraph.graph import StateGraph

graph = StateGraph(ConversationState)
# ... define nodes ...
compiled = graph.compile(checkpointer=checkpointer)

# Save state - TTL starts
config = {"configurable": {"thread_id": thread_id}}
compiled.invoke(state, config=config)

# Restore state - TTL extends to 48h (touch on access)
state = compiled.get_state(config)
```

## Key Features

### 1. Cryptographic Identities

- user_id: stable SHA-256 (64 hex chars)
  - Generated from client_info
  - Persistent across sessions
  - Strict validation

- thread_id: unique HMAC-SHA256 (64 hex chars)
  - Derived from user_id + conversation_seed + server_secret
  - Not predictable (secure)
  - Unique per conversation

### 2. Conversation State

`ConversationState` contains:

- Identifiers: user_id, thread_id
- Messages: list of messages (inherits from MessagesState)
- Recent window: last N full messages
- Pareto summary: compressed history (20%)
- Tool memory: list of tools used
- Current context: conversation state
- Metadata: timestamps, counters

### 3. Smart TTL (Touch on Access)

The Redis checkpointer:

- put(): store state and apply 48h TTL
- get(): restore state and EXTEND TTL to 48h
- Result: active conversations live indefinitely

**Example flow**:

```
Day 0: Create conversation -> TTL = 48h
Day 1: Access conversation -> TTL reset to 48h
Day 3: Access conversation -> TTL reset to 48h
Day 5: No access for 48h  -> Auto-delete
```

## Tests

### Unit Tests

```bash
# Identifiers
pytest tests/memory/test_identifiers.py -v

# State
pytest tests/memory/test_state.py -v
```

### Test Coverage

**test_identifiers.py**:

- Generate user_id (SHA-256)
- Generate thread_id (HMAC-SHA256)
- Format validation
- Determinism with seeds
- Uniqueness without seeds

**test_state.py**:

- Initial state creation
- Add tool executions
- Retrieve recent executions
- Find by doc_id
- Metadata updates

## Configuration

Add to `.env`:

```bash
# Memory System
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
MEMORY_TTL=172800  # 48 hours
THREAD_SECRET=your-secret-key-here  # Generate with: openssl rand -hex 32
```

## Full Implementation Status

### Phase 1: Foundations (COMPLETED)
- `core/identifiers.py` - Cryptographic ID generation
- `core/state.py` - ConversationState definition
- `core/checkpointer.py` - Redis checkpointer with TTL

### Phase 2: Compression + Tool Memory (COMPLETED)
- `compression/pareto.py` - 80/20 compression
- `compression/summarizer.py` - LLM summarizer (LFM2-1.2B)
- `layers/tool_memory.py` - Tool memory management

### Phase 3: Context Assembly (COMPLETED)
- `context/builder.py` - Hierarchical context builder

### Phase 4-5: ChatMemory (COMPLETED)
- `snapshot.py` - Compressed snapshot creation
- `storage/chat_memory_schema.py` - Weaviate schema for ChatMemory
- `storage/chat_memory_persistence.py` - Snapshot persistence
- `retrieval/cross_chat.py` - Cross-chat retrieval

### Phase 6: RRF + MMR (COMPLETED)
- `retrieval/rrf_fusion.py` - Reciprocal Rank Fusion
- `retrieval/mmr.py` - Maximal Marginal Relevance (anti-echo)
- `integration.py` - ChatMemoryManager integration

### Pending: API Integration
- [ ] Modify `src/api/ollama/router.py` to use ChatMemory
- [ ] Integrate snapshot creation into the conversation flow
- [ ] Add cross-chat retrieval to the RAG pipeline
- [ ] Configure automatic cleanup of expired snapshots

## Troubleshooting

### ModuleNotFoundError: No module named 'langgraph'

```bash
pip install langgraph langgraph-checkpoint-redis
```

### Redis connection refused

```bash
# Verify Redis is running
systemctl --user status redis
# Or with podman-compose
podman-compose up -d redis
```

### Tests fail with Redis

```bash
# Verify connection
redis-cli -h 127.0.0.1 -p 6379 ping
# Should respond: PONG
```

## References

- [Full plan](../../docs/MEMORY_SYSTEM_IMPLEMENTATION_PLAN.md)
- [LangGraph Docs](https://langchain-ai.github.io/langgraph/)
- [Redis Checkpointer](https://langchain-ai.github.io/langgraph/how-tos/persistence/)

## Phase 1 Checklist

- [x] Dependencies added to requirements.txt
- [x] Directory structure created
- [x] identifiers.py implemented and tested
- [x] state.py implemented and tested
- [x] checkpointer.py implemented
- [x] Unit tests created
- [x] Verification script created
- [x] Documentation completed

**Status**: PHASE 1 COMPLETED

**Next step**: Install dependencies and start Phase 2.
