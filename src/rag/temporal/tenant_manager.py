"""Manages temporal tenants in Weaviate for file-based RAG.

Temporal tenants have a TTL and are automatically cleaned up.
Each thread gets its own isolated tenant: temp_{thread_id}
"""
import logging
import time
from typing import List, Optional, Dict, Any
import weaviate
from weaviate.classes.tenants import Tenant, TenantActivityStatus

logger = logging.getLogger(__name__)


class TemporalTenantManager:
    """Manages temporal multi-tenancy for uploaded files in Weaviate."""

    def __init__(
        self,
        weaviate_client: weaviate.WeaviateClient,
        collection_name: str,
        ttl_seconds: int = 86400,  # 24 hours default
    ):
        """Initialize temporal tenant manager.

        Args:
            weaviate_client: Weaviate client instance
            collection_name: Name of the collection to use
            ttl_seconds: Time-to-live for temporal tenants (default: 24h)
        """
        self.client = weaviate_client
        self.collection_name = collection_name
        self.ttl_seconds = ttl_seconds

        logger.info(
            f"TemporalTenantManager initialized: collection={collection_name}, ttl={ttl_seconds}s"
        )

    def create_temporal_tenant(self, thread_id: str) -> str:
        """Create a new temporal tenant for a thread.

        Args:
            thread_id: Thread identifier

        Returns:
            Tenant name (temp_{thread_id})
        """
        tenant_name = f"temp_{thread_id}"

        try:
            collection = self.client.collections.get(self.collection_name)

            # Check if tenant already exists (handle both str and object with .name attribute)
            existing_tenants = collection.tenants.get()
            tenant_names = [t if isinstance(t, str) else t.name for t in existing_tenants]
            if tenant_name in tenant_names:
                logger.info(f"Temporal tenant already exists: {tenant_name}")
                return tenant_name

            # Create new tenant
            collection.tenants.create(
                tenants=[
                    Tenant(
                        name=tenant_name,
                        activity_status=TenantActivityStatus.ACTIVE,
                    )
                ]
            )

            logger.info(f"Created temporal tenant: {tenant_name}")
            return tenant_name

        except Exception as e:
            logger.error(f"Failed to create temporal tenant {tenant_name}: {e}")
            raise

    def get_or_create_temporal_tenant(self, thread_id: str) -> str:
        """Get existing or create new temporal tenant for a thread.

        Args:
            thread_id: Thread identifier

        Returns:
            Tenant name
        """
        tenant_name = f"temp_{thread_id}"

        try:
            collection = self.client.collections.get(self.collection_name)
            existing_tenants = collection.tenants.get()

            # Check if exists (handle both str and object with .name attribute)
            tenant_names = [t if isinstance(t, str) else t.name for t in existing_tenants]
            if tenant_name in tenant_names:
                logger.debug(f"Using existing temporal tenant: {tenant_name}")
                return tenant_name

            # Create if not exists
            return self.create_temporal_tenant(thread_id)

        except Exception as e:
            logger.error(f"Failed to get/create temporal tenant {tenant_name}: {e}")
            raise

    def delete_temporal_tenant(self, thread_id: str) -> bool:
        """Delete a temporal tenant and all its data.

        Args:
            thread_id: Thread identifier

        Returns:
            True if deleted successfully, False otherwise
        """
        tenant_name = f"temp_{thread_id}"

        try:
            collection = self.client.collections.get(self.collection_name)
            collection.tenants.remove(tenants=[tenant_name])

            logger.info(f"Deleted temporal tenant: {tenant_name}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete temporal tenant {tenant_name}: {e}")
            return False

    def list_temporal_tenants(self) -> List[str]:
        """List all temporal tenants.

        Returns:
            List of temporal tenant names
        """
        try:
            collection = self.client.collections.get(self.collection_name)
            all_tenants = collection.tenants.get()

            # Filter only temporal tenants (start with "temp_")
            # Handle both str and object with .name attribute
            temporal_tenants = [
                (t if isinstance(t, str) else t.name)
                for t in all_tenants
                if (t if isinstance(t, str) else t.name).startswith("temp_")
            ]

            logger.debug(f"Found {len(temporal_tenants)} temporal tenants")
            return temporal_tenants

        except Exception as e:
            logger.error(f"Failed to list temporal tenants: {e}")
            return []

    def cleanup_expired_tenants(self, redis_client, tenant_ttl_key_prefix: str = "tenant_created:") -> int:
        """Cleanup temporal tenants that have exceeded their TTL.

        Args:
            redis_client: Redis client for tracking tenant creation times
            tenant_ttl_key_prefix: Redis key prefix for tenant timestamps

        Returns:
            Number of tenants deleted
        """
        deleted_count = 0
        current_time = time.time()

        temporal_tenants = self.list_temporal_tenants()

        for tenant_name in temporal_tenants:
            # Get creation time from Redis
            creation_time_key = f"{tenant_ttl_key_prefix}{tenant_name}"
            creation_time = redis_client.get(creation_time_key)

            if creation_time is None:
                # No timestamp found, set it now (grace period)
                redis_client.setex(creation_time_key, self.ttl_seconds, current_time)
                logger.warning(f"No creation time for {tenant_name}, setting grace period")
                continue

            creation_time = float(creation_time)
            age = current_time - creation_time

            # Check if expired
            if age > self.ttl_seconds:
                logger.info(
                    f"Deleting expired tenant {tenant_name} (age: {age:.0f}s, ttl: {self.ttl_seconds}s)"
                )

                # Delete tenant
                if self.delete_temporal_tenant(tenant_name.replace("temp_", "")):
                    # Delete Redis tracking key
                    redis_client.delete(creation_time_key)
                    deleted_count += 1

        if deleted_count > 0:
            logger.info(f"Cleanup completed: deleted {deleted_count} expired tenants")

        return deleted_count

    def get_tenant_stats(self, tenant_name: str) -> Optional[Dict[str, Any]]:
        """Get statistics for a temporal tenant.

        Args:
            tenant_name: Tenant name (with or without temp_ prefix)

        Returns:
            Dictionary with tenant statistics or None if not found
        """
        if not tenant_name.startswith("temp_"):
            tenant_name = f"temp_{tenant_name}"

        try:
            collection = self.client.collections.get(self.collection_name)

            # Query with tenant filter
            tenant_collection = collection.with_tenant(tenant_name)
            # Get object count
            result = tenant_collection.aggregate.over_all(total_count=True)

            return {
                "tenant_name": tenant_name,
                "object_count": result.total_count,
                "collection": self.collection_name,
            }

        except Exception as e:
            logger.error(f"Failed to get stats for tenant {tenant_name}: {e}")
            return None


def create_temporal_tenant_manager(
    weaviate_client: weaviate.WeaviateClient,
    collection_name: str,
    ttl_seconds: int = 86400,
) -> TemporalTenantManager:
    """Factory function to create TemporalTenantManager.

    Args:
        weaviate_client: Weaviate client instance
        collection_name: Collection name
        ttl_seconds: TTL for temporal tenants

    Returns:
        TemporalTenantManager instance
    """
    return TemporalTenantManager(
        weaviate_client=weaviate_client,
        collection_name=collection_name,
        ttl_seconds=ttl_seconds,
    )
