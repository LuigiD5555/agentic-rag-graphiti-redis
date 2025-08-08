"""Module that interacts with Qdrant vector database for storing and searching documents."""
from typing import Optional, cast
import hashlib
from qdrant_client import QdrantClient
from qdrant_client.models import VectorParams, Distance, PointStruct


class VectorStoreService:
    """
    High-level wrapper for Qdrant vector database.
    Handles collection creation, upserts (insert or update), and similarity search.
    """

    def __init__(
        self,
        config,
        collection_name: Optional[str] = None,
        vector_size: Optional[int] = None
    ):
        """
        :param config: Config object with QDRANT_URL, optional QDRANT_COLLECTION, EMBEDDING_DIM
        :param collection_name: Optional override for collection name
        :param vector_size: Optional override for vector size
        """
        self.client = QdrantClient(url=config.QDRANT_URL)
        self.collection_name: str = str(
            collection_name or getattr(config, "QDRANT_COLLECTION", "rag_docs")
        )
        self.vector_size: int = int(vector_size or cast(int, getattr(config, "EMBEDDING_DIM", 768)))

        # Ensure collection exists
        self._ensure_collection()

    def _ensure_collection(self):
        """Create collection if it does not exist in Qdrant (safe for offline mode)"""
        try:
            if not self.client.collection_exists(self.collection_name):
                self.client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=VectorParams(
                        size=self.vector_size,
                        distance=Distance.COSINE
                    ),
                )
        except RuntimeError as e:
            # Log the warning instead of failing hard (useful for tests/offline mode)
            print(f"WARNING: Could not verify or create collection '{self.collection_name}': {e}")

    def _generate_id(self, text: str) -> str:
        """Generate deterministic ID from text content (MD5 hash)"""
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    def upsert(self, key: str | None, vector: list[float], metadata: dict[str, str]):
        """
        Insert or update a vector with metadata.
        - If 'key' is provided, it is used as document ID.
        - Otherwise, an ID is generated from `metadata["content"]`.
        """
        doc_id = key if key else self._generate_id(metadata.get("content", ""))

        enriched_metadata = metadata.copy()
        enriched_metadata["external_id"] = key if key else doc_id

        point = PointStruct(
            id=doc_id,
            vector=vector,
            payload=enriched_metadata
        )

        self.client.upsert(
            collection_name=self.collection_name,
            points=[point],
        )

    def search(self, vector: list[float], top_k: int = 5):
        """
        Search for the closest vectors to the given vector.
        :param vector: The query vector
        :param top_k: Number of closest matches to return
        """
        return self.client.search(
            collection_name=self.collection_name,
            query_vector=vector,
            limit=top_k
        )
