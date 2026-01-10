# Resumable Checkpoint System

This module implements a complete resumable checkpoint system for both scanning and ingestion phases of the RAG pipeline.

## Architecture Overview

The checkpoint system consists of four main components:

### 1. ScanCheckpointer (Lightweight)
Enables resumable directory scanning after interruptions.

**Features:**
- Redis-backed queue of pending directories
- Visited directory tracking (idempotency)
- run_id isolation for concurrent scans
- Progress saving every N directories

**Redis Keys:**
```
scan:run:{run_id}:pending   # LIST - Pending directories
scan:run:{run_id}:visited   # SET - Visited directories
scan:run:{run_id}:files     # LIST - Discovered files
scan:run:{run_id}:meta      # HASH - Run metadata
scan:runs:active            # ZSET - Active run index
```

### 2. IngestQueue (Heavier)
Persistent job queue using Redis Streams for resumable ingestion.

**Features:**
- Redis Streams with consumer groups
- Automatic retry with exponential backoff
- Dead letter queue (DLQ) for failed jobs
- Job claiming for abandoned work

**Redis Keys:**
```
ingest:queue         # STREAM - Main job queue
ingest:dlq           # STREAM - Dead letter queue
ingest:stats         # HASH - Queue statistics
ingest:consumers     # HASH - Active consumers
```

### 3. ChunkRegistry
Granular chunk-level tracking for precise ingestion control.

**Features:**
- Deterministic chunk_id generation
- Per-chunk status tracking (pending/processing/completed/failed)
- Chunk to file relationship tracking
- Vector ID reverse lookup

**Chunk ID Generation:**
```python
chunk_id = sha256(file_id + chunk_index + content_hash)[:32]
```

### 4. FileRegistryExtensions
Extended file tracking with run_id support.

**Features:**
- Track which run_id last saw each file
- Detect deleted files between runs
- Associate files with scan/ingestion runs
- Manage chunk relationships

## Usage

### Basic Integration

#### 1. Resumable Scanning

```python
from src.storage.cache.ingestion import IngestionCacheManager
from src.ingestion.checkpoint import ScanCheckpointer
from src.ingestion.discovery import DiscoveryService

# Initialize components
cache_manager = IngestionCacheManager()
checkpointer = ScanCheckpointer(cache_manager.redis)

# Start a new scan run (or resume existing)
run_id = checkpointer.start_new_run(
    root_paths=["/path/to/docs"],
    options_hash="abc123"
)

# Initialize discovery service with checkpointer
discovery = DiscoveryService(
    cache_manager=cache_manager,
    scan_checkpointer=checkpointer
)

# Use resumable scanning in DirectoryScanner
# scanner.scan_directory_resumable() will use the checkpointer
```

#### 2. Resumable Ingestion

```python
from src.storage.cache.ingestion import IngestionCacheManager
from src.ingestion.checkpoint import IngestQueue, ChunkRegistry
from src.ingestion.pipeline import IngestionPipeline

# Initialize components
cache_manager = IngestionCacheManager()
ingest_queue = IngestQueue(cache_manager.redis)
chunk_registry = ChunkRegistry(cache_manager.redis)

# Create pipeline with checkpoint support
pipeline = IngestionPipeline(
    embedding_service=embedding_service,
    vector_store=vector_store,
    options=options,
    cache_manager=cache_manager,
    ingest_queue=ingest_queue,
    chunk_registry=chunk_registry,
)

# Use resumable ingestion
ingested, failed, enqueued = pipeline.ingest_files_resumable(
    file_paths=["/path/to/file1.txt", "/path/to/file2.md"],
    run_id="ingest_2024_01_10",
    scan_run_id="scan_2024_01_10"  # Optional
)

print(f"Enqueued {enqueued} jobs, {ingested} succeeded, {failed} failed")
```

### CLI Commands

The checkpoint CLI provides commands for monitoring and managing checkpoint operations:

#### Scan Commands

```bash
# List all active scan runs
python -m src.ingestion.checkpoint.checkpoint_cli scan:list

# Show detailed status of a scan run
python -m src.ingestion.checkpoint.checkpoint_cli scan:status <run_id>

# Resume an interrupted scan
python -m src.ingestion.checkpoint.checkpoint_cli scan:resume <run_id>
```

#### Queue Commands

```bash
# Show queue statistics
python -m src.ingestion.checkpoint.checkpoint_cli queue:stats

# List pending jobs
python -m src.ingestion.checkpoint.checkpoint_cli queue:list --limit 20

# List failed jobs in dead letter queue
python -m src.ingestion.checkpoint.checkpoint_cli queue:dlq --limit 20

# Clear all queue data (DANGEROUS)
python -m src.ingestion.checkpoint.checkpoint_cli queue:clear --force
```

#### Chunk Commands

```bash
# Show chunk registry statistics
python -m src.ingestion.checkpoint.checkpoint_cli chunk:stats

# Show chunk status for a specific file
python -m src.ingestion.checkpoint.checkpoint_cli chunk:file <file_id>
```

## Workflow Examples

### Example 1: Resuming After Interruption

**Scenario:** Scan was interrupted after processing 50% of directories.

```python
# List active runs to find the interrupted one
checkpointer = ScanCheckpointer(redis_client)
runs = checkpointer.list_runs()

for run in runs:
    if run['status'] == 'interrupted':
        print(f"Found interrupted run: {run['run_id']}")
        print(f"  Pending directories: {run['dirs_pending']}")
        print(f"  Files found so far: {run['files_found']}")

# Resume the run
run_id = "scan_interrupted_run_123"
scan_run = checkpointer.resume_run(run_id)

if scan_run:
    # Continue scanning from where it left off
    # The scanner will use the pending queue instead of starting over
    pass
```

### Example 2: Parallel Workers Processing Queue

**Scenario:** Multiple workers processing the same ingestion queue.

```python
# Worker 1
queue = IngestQueue(redis_client)
consumer_name = "worker_1"

while True:
    jobs = queue.dequeue(consumer_name, count=10, block=5000)

    if not jobs:
        break

    for job_id, job in jobs:
        try:
            # Process the file
            success = process_file(job.file_path)

            if success:
                queue.acknowledge(job_id, success=True)
            else:
                queue.acknowledge(job_id, success=False, error="Processing failed")
        except Exception as e:
            queue.acknowledge(job_id, success=False, error=str(e))
```

### Example 3: Monitoring Progress

```python
# Get queue statistics
queue = IngestQueue(redis_client)
stats = queue.get_stats()

print(f"Ingestion Progress:")
print(f"  Total Enqueued: {stats['total_enqueued']}")
print(f"  Completed: {stats['completed']} ({stats['completed']/stats['total_enqueued']*100:.1f}%)")
print(f"  Failed: {stats['failed']}")
print(f"  Pending: {stats['pending']}")
print(f"  Processing: {stats['processing']}")

# Check chunk-level progress for a specific file
chunk_registry = ChunkRegistry(redis_client)
file_id = "abc123def456..."  # Content hash

progress = chunk_registry.get_file_progress(file_id)
print(f"\nFile Progress ({file_id}):")
print(f"  Chunks: {progress['completed']}/{progress['total']} ({progress['progress_pct']:.1f}%)")
print(f"  Failed: {progress['failed']}")
```

### Example 4: Handling Failed Jobs

```python
# Check dead letter queue
queue = IngestQueue(redis_client)
dlq_length = queue.get_dlq_length()

print(f"Failed jobs in DLQ: {dlq_length}")

# Inspect failed jobs (using Redis directly)
messages = redis_client.xrange(queue.DLQ_KEY, min="-", max="+", count=10)

for msg_id, msg_data in messages:
    print(f"Failed: {msg_data['file_path']}")
    print(f"  Error: {msg_data['error']}")
    print(f"  Retry Count: {msg_data['retry_count']}")

    # Optionally: Re-enqueue for manual retry
    # queue.enqueue(msg_data['file_path'], msg_data['run_id'])
```

## Configuration

### Environment Variables

```bash
# Redis connection
REDIS_URL=redis://localhost:6379/0

# Checkpoint TTL (time-to-live)
CHECKPOINT_TTL=2592000  # 30 days in seconds

# Queue settings
INGEST_MAX_RETRIES=3
INGEST_RETRY_BACKOFF_BASE=2  # seconds
INGEST_CLAIM_MIN_IDLE_TIME=60000  # milliseconds
```

### Tuning Parameters

**ScanCheckpointer:**
- `ttl`: How long to keep checkpoint data (default: 30 days)
- `progress_every`: Save progress every N directories (default: 100)

**IngestQueue:**
- `max_retries`: Maximum retry attempts before DLQ (default: 3)
- `RETRY_BACKOFF_BASE`: Base for exponential backoff (default: 2 seconds)
- `CLAIM_MIN_IDLE_TIME`: Min idle time before claiming abandoned jobs (default: 60 seconds)
- `STREAM_MAXLEN`: Approximate max entries in stream (default: 100,000)

**ChunkRegistry:**
- `ttl`: How long to keep chunk metadata (default: 30 days)

## Best Practices

### 1. Use Unique run_ids

Always use unique, descriptive run_ids to avoid conflicts:

```python
import time

run_id = f"scan_{int(time.time())}"
# or
run_id = f"scan_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
```

### 2. Monitor Queue Statistics

Regularly check queue stats to identify bottlenecks:

```python
stats = queue.get_stats()

if stats['failed'] > stats['completed'] * 0.1:  # More than 10% failed
    print("WARNING: High failure rate detected!")

if stats['processing'] > 0 and stats['pending'] == 0:
    # Jobs stuck in processing state - may need to claim abandoned
    abandoned = queue.claim_abandoned(consumer_name)
```

### 3. Clean Up Completed Runs

Periodically clean up old completed runs to free up Redis memory:

```python
# List all runs
runs = checkpointer.list_runs()

# Delete old completed runs
for run in runs:
    if run['status'] == 'completed' and is_older_than_30_days(run['created_at']):
        redis_client.delete(f"scan:run:{run['run_id']}:*")
```

### 4. Handle DLQ Proactively

Don't let the DLQ grow unbounded:

```python
dlq_length = queue.get_dlq_length()

if dlq_length > 100:
    # Investigate and fix root cause
    # Option 1: Manual intervention
    # Option 2: Clear DLQ after analysis
    pass
```

## Troubleshooting

### Issue: Scan Not Resuming

**Symptoms:** `resume_run()` returns None

**Causes:**
- run_id doesn't exist
- Run already completed
- Redis keys expired

**Solution:**
```python
# Check if run exists
runs = checkpointer.list_runs()
print([r['run_id'] for r in runs])

# Check Redis keys manually
redis_client.keys("scan:run:*")
```

### Issue: Jobs Stuck in Processing

**Symptoms:** `queue:stats` shows high processing count but no progress

**Causes:**
- Consumer crashed without acknowledging
- Network interruption

**Solution:**
```python
# Claim abandoned jobs
abandoned = queue.claim_abandoned(consumer_name, count=100)
print(f"Claimed {len(abandoned)} abandoned jobs")

# Process them
for job_id, job in abandoned:
    # Process and acknowledge
    pass
```

### Issue: High Failure Rate

**Symptoms:** Many jobs in DLQ

**Causes:**
- Embedding service down
- File format issues
- Bugs in processing logic

**Solution:**
```python
# Inspect DLQ messages
messages = redis_client.xrange(queue.DLQ_KEY, "-", "+", count=10)

# Analyze error patterns
errors = [msg_data['error'] for _, msg_data in messages]
from collections import Counter
print(Counter(errors))
```

## Performance Considerations

### Redis Memory Usage

The checkpoint system stores metadata in Redis. Approximate memory usage:

- **ScanCheckpointer:** ~1KB per directory + ~100B per file
- **IngestQueue:** ~500B per job
- **ChunkRegistry:** ~200B per chunk

For a scan with 100,000 files in 10,000 directories:
- Total: ~10MB + ~10MB = 20MB

For ingestion of 100,000 files with avg 10 chunks each:
- Total: ~50MB + ~200MB = 250MB

### Throughput

- **Scanning:** Limited by filesystem I/O, not Redis
- **Ingestion:** Limited by embedding service, not Redis
- **Redis Operations:** ~50,000 ops/sec on commodity hardware

### Scaling

For very large datasets (millions of files):

1. **Use SCAN instead of KEYS**
   ```python
   # Instead of: redis_client.keys("scan:run:*")
   for key in redis_client.scan_iter("scan:run:*"):
       # Process key
   ```

2. **Use Pipelines for Bulk Operations**
   ```python
   pipe = redis_client.pipeline()
   for file_path in file_paths:
       pipe.sadd(f"scan:run:{run_id}:files", file_path)
   pipe.execute()
   ```

3. **Consider Redis Cluster**
   For horizontal scaling across multiple Redis nodes.

## Testing

See the test files in the repository:
- `tests/checkpoint/test_scan_checkpointer.py`
- `tests/checkpoint/test_ingest_queue.py`
- `tests/checkpoint/test_chunk_registry.py`

Run tests:
```bash
pytest tests/checkpoint/ -v
```

## Future Enhancements

Potential improvements for future versions:

1. **Priorities:** Job prioritization in IngestQueue
2. **Batching:** Batch embedding requests for efficiency
3. **Metrics:** Prometheus metrics for monitoring
4. **UI Dashboard:** Web UI for checkpoint management
5. **Auto-cleanup:** Automatic cleanup of old checkpoints
6. **Compression:** Compress large metadata in Redis
7. **Sharding:** Shard queue across multiple streams

## License

See main project LICENSE file.
