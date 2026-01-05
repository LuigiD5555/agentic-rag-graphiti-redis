"""Dual-collection vector store for memory-optimized RAG.

Manages two Weaviate collections:
- Small collection (384 dims) for general/non-critical documents
- Large collection (768 dims) for important documents

This reduces memory usage by ~40-50% while maintaining quality for critical content.
"""

from typing import List, Dict, Any, Optional
import weaviate
from weaviate.classes.config import Configure, Property, DataType
from src.rag.audit import get_logger
from src.rag.importance import DocumentImportanceClassifier, ImportanceLevel

log = get_logger(__name__)


class DualCollectionVectorStore:
    """Vector store with dual collections for memory optimization."""

    def __init__(
        self,
        client: weaviate.WeaviateClient,
        small_collection_name: str,
        large_collection_name: str,
        small_embedding_dim: int = 384,
        large_embedding_dim: int = 768,
        importance_classifier: Optional[DocumentImportanceClassifier] = None,
        enable_multi_tenancy: bool = True,
    ):
        """Initialize dual-collection vector store.

        Args:
            client: Weaviate client instance
            small_collection_name: Name for low-dim collection (e.g., "RAGDocument384")
            large_collection_name: Name for high-dim collection (e.g., "RAGDocument768")
            small_embedding_dim: Dimension for small embeddings (default: 384)
            large_embedding_dim: Dimension for large embeddings (default: 768)
            importance_classifier: Classifier to determine which collection to use
            enable_multi_tenancy: Enable multi-tenancy support
        """
        self.client = client
        self.small_collection_name = small_collection_name
        self.large_collection_name = large_collection_name
        self.small_embedding_dim = small_embedding_dim
        self.large_embedding_dim = large_embedding_dim
        self.classifier = importance_classifier or DocumentImportanceClassifier()
        self.enable_multi_tenancy = enable_multi_tenancy

        # Initialize collections
        self._ensure_collections()

        log.info(
            "DualCollectionVectorStore initialized: small=%s (%dd), large=%s (%dd), "
            "multi_tenancy=%s",
            small_collection_name, small_embedding_dim,
            large_collection_name, large_embedding_dim,
            enable_multi_tenancy
        )

    def _ensure_collections(self):
        """Ensure both collections exist with proper schema."""
        for collection_name, embedding_dim in [
            (self.small_collection_name, self.small_embedding_dim),
            (self.large_collection_name, self.large_embedding_dim),
        ]:
            if not self.client.collections.exists(collection_name):
                log.info(
                    "Creating collection %s with %d dimensions",
                    collection_name, embedding_dim
                )
                self._create_collection(collection_name, embedding_dim)
            else:
                log.info("Collection %s already exists", collection_name)

    def _create_collection(self, collection_name: str, embedding_dim: int):
        """Create a Weaviate collection with the specified schema.

        Args:
            collection_name: Name of the collection
            embedding_dim: Vector dimension
        """
        properties = [
            Property(name="text", data_type=DataType.TEXT),
            Property(name="source", data_type=DataType.TEXT),
            Property(name="chunk_index", data_type=DataType.INT),
            Property(name="file_id", data_type=DataType.TEXT),
            Property(name="file_path", data_type=DataType.TEXT),
            Property(name="importance_level", data_type=DataType.TEXT),
        ]

        vectorizer_config = Configure.Vectorizer.none()

        if self.enable_multi_tenancy:
            self.client.collections.create(
                name=collection_name,
                properties=properties,
                vectorizer_config=vectorizer_config,
                vector_index_config=Configure.VectorIndex.hnsw(
                    distance_metric="cosine",
                    ef_construction=128,
                    max_connections=32,
                ),
                multi_tenancy_config=Configure.multi_tenancy(enabled=True),
            )
        else:
            self.client.collections.create(
                name=collection_name,
                properties=properties,
                vectorizer_config=vectorizer_config,
                vector_index_config=Configure.VectorIndex.hnsw(
                    distance_metric="cosine",
                    ef_construction=128,
                    max_connections=32,
                ),
            )

        log.info("Created collection %s with %d dimensions", collection_name, embedding_dim)

    def get_collection_for_file(self, file_path: str) -> str:
        """Determine which collection to use for a file.

        Args:
            file_path: Path to the file

        Returns:
            Collection name (small or large)
        """
        importance = self.classifier.classify(file_path)
        if importance == ImportanceLevel.HIGH:
            return self.large_collection_name
        else:
            return self.small_collection_name

    def get_embedding_dim_for_file(self, file_path: str) -> int:
        """Get the embedding dimension for a file.

        Args:
            file_path: Path to the file

        Returns:
            Embedding dimension (384 or 768)
        """
        collection = self.get_collection_for_file(file_path)
        if collection == self.large_collection_name:
            return self.large_embedding_dim
        else:
            return self.small_embedding_dim

    def insert_batch(
        self,
        collection_name: str,
        chunks: List[Dict[str, Any]],
        tenant: Optional[str] = None,
    ) -> int:
        """Insert a batch of chunks into the specified collection.

        Args:
            collection_name: Target collection name
            chunks: List of chunk dictionaries with 'text', 'vector', 'metadata'
            tenant: Optional tenant ID

        Returns:
            Number of chunks successfully inserted
        """
        if not chunks:
            return 0

        collection = self.client.collections.get(collection_name)
        if tenant and self.enable_multi_tenancy:
            collection = collection.with_tenant(tenant)

        # Prepare objects for batch insert
        objects = []
        for chunk in chunks:
            obj = {
                "properties": {
                    "text": chunk.get("text", ""),
                    "source": chunk.get("source", ""),
                    "chunk_index": chunk.get("chunk_index", 0),
                    "file_id": chunk.get("file_id", ""),
                    "file_path": chunk.get("file_path", ""),
                    "importance_level": chunk.get("importance_level", "unknown"),
                },
                "vector": chunk.get("vector", []),
            }
            objects.append(obj)

        # Batch insert
        try:
            with collection.batch.dynamic() as batch:
                for obj in objects:
                    batch.add_object(
                        properties=obj["properties"],
                        vector=obj["vector"],
                    )

            log.info(
                "Inserted %d chunks into collection %s (tenant=%s)",
                len(chunks), collection_name, tenant or "default"
            )
            return len(chunks)

        except Exception as e:
            log.error(
                "Failed to insert batch into %s: %s",
                collection_name, e, exc_info=True
            )
            return 0

    def get_statistics(self) -> Dict[str, Any]:
        """Get statistics for both collections.

        Returns:
            Dictionary with collection statistics
        """
        stats = {}

        for collection_name in [self.small_collection_name, self.large_collection_name]:
            try:
                collection = self.client.collections.get(collection_name)
                result = collection.aggregate.over_all(total_count=True)
                total = result.total_count if result else 0

                stats[collection_name] = {
                    "total_documents": total,
                    "embedding_dim": (
                        self.small_embedding_dim
                        if collection_name == self.small_collection_name
                        else self.large_embedding_dim
                    ),
                }
            except Exception as e:
                log.error(f"Failed to get stats for {collection_name}: {e}")
                stats[collection_name] = {"error": str(e)}

        # Calculate memory savings estimate
        small_count = stats.get(self.small_collection_name, {}).get("total_documents", 0)
        large_count = stats.get(self.large_collection_name, {}).get("total_documents", 0)

        if small_count + large_count > 0:
            # Estimate memory usage (rough calculation)
            # Each float32 = 4 bytes
            small_mem_mb = (small_count * self.small_embedding_dim * 4) / (1024 * 1024)
            large_mem_mb = (large_count * self.large_embedding_dim * 4) / (1024 * 1024)
            total_mem_mb = small_mem_mb + large_mem_mb

            # Compare to if everything used large embeddings
            all_large_mem_mb = (
                (small_count + large_count) * self.large_embedding_dim * 4
            ) / (1024 * 1024)

            savings_mb = all_large_mem_mb - total_mem_mb
            savings_pct = (savings_mb / all_large_mem_mb * 100) if all_large_mem_mb > 0 else 0

            stats["memory_estimate"] = {
                "small_collection_mb": round(small_mem_mb, 2),
                "large_collection_mb": round(large_mem_mb, 2),
                "total_mb": round(total_mem_mb, 2),
                "if_all_large_mb": round(all_large_mem_mb, 2),
                "savings_mb": round(savings_mb, 2),
                "savings_percentage": round(savings_pct, 2),
            }

        return stats


__all__ = ["DualCollectionVectorStore"]
