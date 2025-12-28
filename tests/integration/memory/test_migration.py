#!/usr/bin/env python3
"""Test startup migration from Redis to ChatMemory.

Simula conversaciones antiguas en Redis y verifica que se migren
automáticamente a Weaviate en el arranque.
"""
import sys
import time
import pickle
import weaviate
from redis import Redis
from src.rag.engine import AppConfig
from src.memory.integration import create_chat_memory_manager
from src.memory.snapshot_scheduler import create_snapshot_scheduler
from src.memory.core.checkpointer import create_checkpointer
from src.memory.startup_migrator import migrate_redis_conversations_on_startup
from src.rag.embeddings_factory import get_embedding_service


def create_test_checkpoint(thread_id: str, user_id: str, age_hours: float):
    """Create a test checkpoint in Redis.

    Args:
        thread_id: Thread ID
        user_id: User ID
        age_hours: Age in hours (how old the checkpoint should be)
    """
    # Create checkpoint data matching LangGraph format
    timestamp = time.time() - (age_hours * 3600)

    checkpoint = {
        "v": 1,
        "ts": timestamp,
        "channel_values": {
            "user_id": user_id,
            "thread_id": thread_id,
            "messages": [
                {"role": "user", "content": f"Test message 1 for thread {thread_id[:8]}"},
                {"role": "assistant", "content": f"Response 1 for thread {thread_id[:8]}"},
                {"role": "user", "content": f"Test message 2 for thread {thread_id[:8]}"},
                {"role": "assistant", "content": f"Response 2 for thread {thread_id[:8]}"},
            ],
            "tool_memory": {},
            "summary": None,
        },
        "channel_versions": {},
        "versions_seen": {},
    }

    return checkpoint, timestamp


def main():
    print("=== Test Startup Migration ===\n")

    # 1. Setup Redis
    print("1. Setting up Redis test data...")
    redis_client = Redis(host="127.0.0.1", port=6379, db=0)

    try:
        # Create test checkpoints with different ages
        test_cases = [
            ("thread_old_1", "user_test_1", 48.0),  # 48 hours old - SHOULD migrate
            ("thread_old_2", "user_test_2", 30.0),  # 30 hours old - SHOULD migrate
            ("thread_new_1", "user_test_3", 12.0),  # 12 hours old - should NOT migrate
            ("thread_new_2", "user_test_4", 6.0),   # 6 hours old - should NOT migrate
        ]

        created = 0
        for thread_id, user_id, age_hours in test_cases:
            checkpoint, timestamp = create_test_checkpoint(thread_id, user_id, age_hours)
            key = f"checkpoint:default:{thread_id}"

            # Save to Redis
            redis_client.set(key, pickle.dumps(checkpoint))

            created += 1
            print(f"   ✓ Created checkpoint: {thread_id} (age: {age_hours}h)")

        print(f"   Created {created} test checkpoints\n")

    except Exception as e:
        print(f"   ✗ Error creating test data: {e}\n")
        return 1

    # 2. Initialize components
    print("2. Initializing components...")
    try:
        config = AppConfig()

        # Connect to Weaviate
        client = weaviate.connect_to_local(
            host="127.0.0.1",
            port=8080,
            grpc_port=50051,
        )

        # Create embedding service
        from src.rag.conf import Config as RAGConfig
        rag_config = RAGConfig()
        embedding_service = get_embedding_service(rag_config)

        # Create ChatMemory manager
        manager = create_chat_memory_manager(
            weaviate_client=client,
            embedding_service=embedding_service,
        )

        # Create snapshot scheduler
        scheduler = create_snapshot_scheduler(snapshot_interval=86400)

        # Create checkpointer
        checkpointer = create_checkpointer(
            redis_host="127.0.0.1",
            redis_port=6379,
            ttl_seconds=172800,
        )

        print("   ✓ Components initialized\n")

    except Exception as e:
        print(f"   ✗ Error initializing components: {e}\n")
        return 1

    # 3. Run migration
    print("3. Running startup migration...")
    try:
        stats = migrate_redis_conversations_on_startup(
            checkpointer=checkpointer,
            chat_memory_manager=manager,
            snapshot_scheduler=scheduler,
            age_threshold=86400,  # 24 hours
        )

        print(f"   ✓ Migration completed:")
        print(f"     - Scanned: {stats['scanned']}")
        print(f"     - Migrated: {stats['migrated']}")
        print(f"     - Skipped: {stats['skipped']}")
        print(f"     - Errors: {stats['errors']}\n")

        # Verify results
        expected_migrated = 2  # thread_old_1 and thread_old_2
        if stats["migrated"] == expected_migrated:
            print(f"   ✓ Expected {expected_migrated} migrations, got {stats['migrated']}\n")
        else:
            print(f"   ✗ Expected {expected_migrated} migrations, got {stats['migrated']}\n")

    except Exception as e:
        print(f"   ✗ Error during migration: {e}\n")
        import traceback
        traceback.print_exc()
        return 1

    # 4. Verify snapshots in Weaviate
    print("4. Verifying snapshots in Weaviate...")
    try:
        from src.memory.storage.chat_memory_schema import CHAT_MEMORY_COLLECTION

        collection = client.collections.get(CHAT_MEMORY_COLLECTION)

        # Query for test snapshots
        results = collection.query.fetch_objects(limit=10)

        migrated_threads = set()
        for obj in results.objects:
            thread_id = obj.properties.get("thread_id")
            if thread_id and thread_id.startswith("thread_"):
                migrated_threads.add(thread_id)
                print(f"   ✓ Found snapshot for thread: {thread_id}")

        print(f"   Found {len(migrated_threads)} migrated snapshots\n")

    except Exception as e:
        print(f"   ✗ Error verifying snapshots: {e}\n")

    # 5. Cleanup
    print("5. Cleanup...")
    try:
        # Delete test checkpoints from Redis
        for thread_id, _, _ in test_cases:
            key = f"checkpoint:default:{thread_id}"
            redis_client.delete(key)

        # Delete test snapshots from Weaviate
        # (They will expire automatically via TTL)

        redis_client.close()
        client.close()
        print("   ✓ Cleanup completed\n")

    except Exception as e:
        print(f"   ✗ Error during cleanup: {e}\n")

    print("=== Test completed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
