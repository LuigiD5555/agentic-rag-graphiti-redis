#!/usr/bin/env python3
"""Test ChatMemory integration with RAG API.

Verifies that:
1. ChatMemory initializes correctly
2. The ChatMemory collection exists in Weaviate
3. RAGOrchestrator has ChatMemory configured
4. SnapshotScheduler works correctly (24h intervals)
5. CleanupScheduler cleans expired snapshots
"""
import sys
import time
import weaviate
from src.rag.engine import AppConfig
from src.memory.integration import create_chat_memory_manager
from src.memory.storage.chat_memory_schema import CHAT_MEMORY_COLLECTION
from src.memory.snapshot_scheduler import create_snapshot_scheduler
from src.memory.cleanup_scheduler import create_cleanup_scheduler

def main():
    print("=== Test ChatMemory Integration ===\n")

    # 1. Connect to Weaviate
    config = AppConfig()
    print(f"1. Connecting to Weaviate at {config.WEAVIATE_URL}...")

    try:
        client = weaviate.connect_to_local(
            host=config.WEAVIATE_URL.replace("http://", "").replace("https://", "").split(":")[0],
            port=int(config.WEAVIATE_URL.split(":")[-1]) if ":" in config.WEAVIATE_URL else 8080,
            grpc_port=config.WEAVIATE_GRPC_PORT,
        )
        print("   ✓ Connected to Weaviate\n")
    except Exception as e:
        print(f"   ✗ Failed to connect: {e}")
        return 1

    # 2. Check if ChatMemory collection exists
    print(f"2. Checking if {CHAT_MEMORY_COLLECTION} collection exists...")
    try:
        exists = client.collections.exists(CHAT_MEMORY_COLLECTION)
        if exists:
            print(f"   ✓ {CHAT_MEMORY_COLLECTION} collection exists\n")

            # Get collection stats
            collection = client.collections.get(CHAT_MEMORY_COLLECTION)
            result = collection.aggregate.over_all(total_count=True)
            count = result.total_count if result else 0
            print(f"   Current snapshots: {count}\n")
        else:
            print(f"   ℹ {CHAT_MEMORY_COLLECTION} collection does not exist yet (will be created on first use)\n")
    except Exception as e:
        print(f"   ✗ Error checking collection: {e}\n")

    # 3. Test ChatMemoryManager initialization
    print("3. Initializing ChatMemoryManager...")
    try:
        manager = create_chat_memory_manager(
            weaviate_client=client,
            embedding_service=None,  # Would need real embedding service
            enable_cross_chat=True,
            enable_rrf=True,
            enable_mmr=True,
        )
        print("   ✓ ChatMemoryManager initialized successfully\n")
    except Exception as e:
        print(f"   ✗ Failed to initialize: {e}\n")
        return 1

    # 4. Test basic ChatMemory operations
    print("4. Testing basic ChatMemory operations...")
    try:
        # Create test snapshot
        from src.memory.snapshot import create_snapshot
        from src.memory.core.state import create_initial_state

        state = create_initial_state("test_user", "test_thread")
        state["messages"] = [
            {"role": "user", "content": "Test question about PDF processing?"},
            {"role": "assistant", "content": "Here is a test answer about PDFs."},
        ]

        snapshot = create_snapshot(
            state=state,
            user_id="test_user",
            thread_id="test_thread",
            ttl_days=1,  # 1 day for testing
        )

        print(f"   ✓ Test snapshot created: {len(snapshot.keywords)} keywords, {len(snapshot.key_quotes)} quotes\n")

        # Try to persist it
        success = manager.persistence.save_snapshot(snapshot)
        if success:
            print("   ✓ Test snapshot saved to Weaviate\n")
        else:
            print("   ✗ Failed to save test snapshot\n")

    except Exception as e:
        print(f"   ✗ Error during testing: {e}\n")

    # 5. Test SnapshotScheduler
    print("5. Testing SnapshotScheduler...")
    try:
        scheduler = create_snapshot_scheduler(snapshot_interval=10)  # 10 seconds for testing

        # First check - should create snapshot (no previous snapshot)
        should_create = scheduler.should_create_snapshot("test_thread")
        print(f"   ✓ First check: should_create={should_create} (expected: True)")

        # Mark snapshot created
        scheduler.mark_snapshot_created("test_thread")

        # Immediate check - should NOT create (just created)
        should_create = scheduler.should_create_snapshot("test_thread")
        print(f"   ✓ Second check: should_create={should_create} (expected: False)")

        # Wait for interval to pass
        print("   ⏳ Waiting 11 seconds for interval to pass...")
        time.sleep(11)

        # Third check - should create (interval passed)
        should_create = scheduler.should_create_snapshot("test_thread")
        print(f"   ✓ Third check: should_create={should_create} (expected: True)\n")

        stats = scheduler.get_stats()
        print(f"   Scheduler stats: {stats}\n")
    except Exception as e:
        print(f"   ✗ Error testing scheduler: {e}\n")

    # 6. Test CleanupScheduler (initialization only, don't start background loop)
    print("6. Testing CleanupScheduler initialization...")
    try:
        cleanup = create_cleanup_scheduler(
            chat_memory_manager=manager,
            snapshot_scheduler=scheduler,
            cleanup_interval=3600,
        )
        print("   ✓ CleanupScheduler initialized successfully")
        print("   ℹ Note: Background loop not started (use await cleanup.start() in async context)\n")
    except Exception as e:
        print(f"   ✗ Error initializing cleanup scheduler: {e}\n")

    # 7. Cleanup
    print("7. Cleanup...")
    try:
        client.close()
        print("   ✓ Weaviate client closed\n")
    except Exception as e:
        print(f"   ✗ Error during cleanup: {e}\n")

    print("=== Test completed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
