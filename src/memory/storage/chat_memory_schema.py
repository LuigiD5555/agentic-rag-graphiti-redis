"""Weaviate schema definition for ChatMemory collection.

ChatMemory stores compressed snapshots of past conversations for cross-chat recall.
Each snapshot represents a conversation turn compressed using Pareto 80/20 principle.

Schema design aligned with Plan Maestro Fase 4.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
import weaviate
from weaviate.classes.config import Configure, Property, DataType

logger = logging.getLogger(__name__)


CHAT_MEMORY_COLLECTION = "ChatMemory"


def create_chat_memory_collection(
    client: weaviate.WeaviateClient,
    vectorizer_model: str = "none",  # We provide embeddings externally
    ttl_days: int = 30,  # Default: 30 days retention
    force_recreate: bool = False,
) -> bool:
    """Create ChatMemory collection in Weaviate.

    Args:
        client: Weaviate client instance
        vectorizer_model: Vectorizer module (default: "none" for external embeddings)
        ttl_days: Default TTL in days for snapshots
        force_recreate: If True, delete and recreate collection

    Returns:
        True if created successfully, False otherwise
    """
    try:
        # Check if collection exists
        exists = client.collections.exists(CHAT_MEMORY_COLLECTION)

        if exists:
            if force_recreate:
                logger.warning(
                    f"Deleting existing {CHAT_MEMORY_COLLECTION} collection"
                )
                client.collections.delete(CHAT_MEMORY_COLLECTION)
            else:
                logger.info(
                    f"{CHAT_MEMORY_COLLECTION} collection already exists"
                )
                return True

        # Create collection with schema
        logger.info(f"Creating {CHAT_MEMORY_COLLECTION} collection...")

        client.collections.create(
            name=CHAT_MEMORY_COLLECTION,
            description="Compressed conversation snapshots for cross-chat recall (Pareto 80/20)",

            # Vectorizer configuration (none = we provide embeddings)
            vectorizer_config=Configure.Vectorizer.none(),

            # Properties schema
            properties=[
                # Core content (indexed for search)
                Property(
                    name="summary_dense",
                    data_type=DataType.TEXT,
                    description="Pareto 80/20 compressed summary (for embedding)",
                    index_searchable=True,
                    index_filterable=False,
                ),
                Property(
                    name="key_quotes",
                    data_type=DataType.TEXT_ARRAY,
                    description="Critical quotes from conversation",
                    index_searchable=True,
                    index_filterable=False,
                ),
                Property(
                    name="keywords",
                    data_type=DataType.TEXT_ARRAY,
                    description="Keywords for BM25 search",
                    index_searchable=True,
                    index_filterable=False,
                ),

                # Metadata (for filtering)
                Property(
                    name="thread_id",
                    data_type=DataType.TEXT,
                    description="Conversation thread ID",
                    index_searchable=False,
                    index_filterable=True,
                ),
                Property(
                    name="user_id",
                    data_type=DataType.TEXT,
                    description="User identifier",
                    index_searchable=False,
                    index_filterable=True,
                ),
                Property(
                    name="timestamp",
                    data_type=DataType.DATE,
                    description="Snapshot creation time (RFC-3339)",
                    index_searchable=False,
                    index_filterable=True,
                ),
                Property(
                    name="ttl_at",
                    data_type=DataType.DATE,
                    description="Expiration time (RFC-3339) - snapshots older than this can be deleted",
                    index_searchable=False,
                    index_filterable=True,
                ),

                # Flags
                Property(
                    name="pinned",
                    data_type=DataType.BOOL,
                    description="If true, exempt from TTL cleanup",
                    index_searchable=False,
                    index_filterable=True,
                ),

                # Statistics (for analytics)
                Property(
                    name="original_message_count",
                    data_type=DataType.INT,
                    description="Number of messages before compression",
                    index_searchable=False,
                    index_filterable=False,
                ),
                Property(
                    name="compression_ratio",
                    data_type=DataType.NUMBER,
                    description="Compression ratio (0.0-1.0)",
                    index_searchable=False,
                    index_filterable=False,
                ),

                # Optional: tool memory snapshot
                Property(
                    name="tool_executions",
                    data_type=DataType.TEXT,  # JSON serialized
                    description="Tool executions from this conversation (JSON)",
                    index_searchable=False,
                    index_filterable=False,
                ),
            ],
        )

        logger.info(
            f"✅ Created {CHAT_MEMORY_COLLECTION} collection successfully "
            f"(TTL: {ttl_days} days)"
        )
        return True

    except Exception as e:
        logger.error(f"Failed to create {CHAT_MEMORY_COLLECTION}: {e}", exc_info=True)
        return False


def get_chat_memory_collection(
    client: weaviate.WeaviateClient,
    auto_create: bool = True,
) -> Optional[weaviate.collections.Collection]:
    """Get ChatMemory collection reference.

    Args:
        client: Weaviate client
        auto_create: Create collection if it doesn't exist

    Returns:
        Collection instance or None if failed
    """
    try:
        exists = client.collections.exists(CHAT_MEMORY_COLLECTION)

        if not exists:
            if auto_create:
                logger.info(
                    f"{CHAT_MEMORY_COLLECTION} not found, creating..."
                )
                created = create_chat_memory_collection(client)
                if not created:
                    return None
            else:
                logger.error(
                    f"{CHAT_MEMORY_COLLECTION} collection does not exist"
                )
                return None

        return client.collections.get(CHAT_MEMORY_COLLECTION)

    except Exception as e:
        logger.error(f"Failed to get {CHAT_MEMORY_COLLECTION}: {e}")
        return None


def calculate_ttl_timestamp(ttl_days: int = 30) -> str:
    """Calculate TTL expiration timestamp.

    Args:
        ttl_days: Days until expiration

    Returns:
        RFC-3339 formatted timestamp
    """
    expiration = datetime.utcnow() + timedelta(days=ttl_days)
    # Weaviate expects RFC-3339 with 'Z' suffix
    return expiration.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def is_expired(ttl_at: str) -> bool:
    """Check if snapshot has expired.

    Args:
        ttl_at: TTL timestamp (RFC-3339)

    Returns:
        True if expired
    """
    try:
        # Parse RFC-3339
        ttl_dt = datetime.fromisoformat(ttl_at.replace("Z", "+00:00"))
        now = datetime.utcnow()
        return now >= ttl_dt
    except Exception as e:
        logger.warning(f"Could not parse ttl_at '{ttl_at}': {e}")
        return False
