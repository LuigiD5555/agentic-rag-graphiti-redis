#!/usr/bin/env python3
"""Test script to diagnose ChatMemory collection initialization."""
import logging
import sys
import weaviate

# Configure detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


def test_chatmemory_initialization():
    """Test ChatMemory collection creation and retrieval."""

    logger.info("=== Testing ChatMemory Collection Initialization ===")

    # Step 1: Connect to Weaviate
    logger.info("Step 1: Connecting to Weaviate...")
    try:
        client = weaviate.connect_to_local(
            host="localhost",
            port=8080,
            grpc_port=50051,
        )
        logger.info("✓ Connected to Weaviate successfully")
    except Exception as e:
        logger.error(f"✗ Failed to connect to Weaviate: {e}", exc_info=True)
        return False

    # Step 2: Check if ChatMemory collection exists
    logger.info("Step 2: Checking if ChatMemory collection exists...")
    try:
        from src.workflows.memory.storage.chat_memory_schema import CHAT_MEMORY_COLLECTION
        exists = client.collections.exists(CHAT_MEMORY_COLLECTION)
        logger.info(f"  ChatMemory exists: {exists}")
    except Exception as e:
        logger.error(f"✗ Failed to check collection existence: {e}", exc_info=True)
        client.close()
        return False

    # Step 3: Create ChatMemory collection
    logger.info("Step 3: Creating ChatMemory collection...")
    try:
        from src.workflows.memory.storage.chat_memory_schema import create_chat_memory_collection
        created = create_chat_memory_collection(client, force_recreate=False)
        if created:
            logger.info("✓ ChatMemory collection created/verified successfully")
        else:
            logger.error("✗ ChatMemory collection creation failed")
            client.close()
            return False
    except Exception as e:
        logger.error(f"✗ Exception during collection creation: {e}", exc_info=True)
        client.close()
        return False

    # Step 4: Retrieve collection reference
    logger.info("Step 4: Retrieving ChatMemory collection reference...")
    try:
        from src.workflows.memory.storage.chat_memory_schema import get_chat_memory_collection
        collection = get_chat_memory_collection(client, auto_create=True)
        if collection:
            logger.info(f"✓ Collection retrieved: {collection.name}")
        else:
            logger.error("✗ Collection retrieval returned None")
            client.close()
            return False
    except Exception as e:
        logger.error(f"✗ Exception during collection retrieval: {e}", exc_info=True)
        client.close()
        return False

    # Step 5: Test ChatMemoryPersistence initialization
    logger.info("Step 5: Testing ChatMemoryPersistence initialization...")
    try:
        from src.workflows.memory.storage.chat_memory_persistence import ChatMemoryPersistence
        persistence = ChatMemoryPersistence(client, embedding_service=None)
        if persistence.collection:
            logger.info("✓ ChatMemoryPersistence initialized successfully")
        else:
            logger.error("✗ ChatMemoryPersistence.collection is None")
            client.close()
            return False
    except Exception as e:
        logger.error(f"✗ Exception during persistence initialization: {e}", exc_info=True)
        client.close()
        return False

    # Cleanup
    logger.info("Closing Weaviate client...")
    client.close()

    logger.info("=== All tests passed! ===")
    return True


if __name__ == "__main__":
    success = test_chatmemory_initialization()
    sys.exit(0 if success else 1)
