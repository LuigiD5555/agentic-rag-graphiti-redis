#!/usr/bin/env python3
"""Migration script to convert existing single-collection data to dual-collection system.

This script:
1. Reads all documents from the existing collection (RAGDocument768)
2. Classifies each document by importance
3. Re-embeds and stores in the appropriate collection (384 or 768 dims)
4. Preserves all metadata and tenant associations
"""

import os
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
import argparse
from tqdm import tqdm

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import weaviate
import src.settings as settings
from src.storage.vector.dual_store import DualCollectionVectorStore
from src.rag.importance import DocumentImportanceClassifier, ImportanceLevel
from src.rag.embeddings_factory import get_embedding_service
from src.providers.factory import ProviderFactory
from src.rag.audit import get_logger

log = get_logger(__name__)


class DualEmbeddingMigrator:
    """Migrates existing embeddings to dual-collection system."""

    def __init__(
        self,
        source_collection: str,
        batch_size: int = 50,
        dry_run: bool = False,
    ):
        """Initialize migrator.

        Args:
            source_collection: Name of existing collection to migrate from
            batch_size: Number of documents to process in each batch
            dry_run: If True, only analyze without migrating
        """
        self.source_collection = source_collection
        self.batch_size = batch_size
        self.dry_run = dry_run

        # Initialize Weaviate client
        host = settings.WEAVIATE_URL.replace("http://", "").replace("https://", "").split(":")[0]
        port = int(settings.WEAVIATE_URL.split(":")[-1]) if ":" in settings.WEAVIATE_URL else 8080
        self.client = weaviate.connect_to_local(
            host=host,
            port=port,
            grpc_port=settings.WEAVIATE_GRPC_PORT,
        )

        # Initialize classifier
        self.classifier = DocumentImportanceClassifier()

        # Initialize dual store
        small_collection = os.getenv("DUAL_EMBEDDINGS_SMALL_COLLECTION", "RAGDocument384")
        large_collection = os.getenv("DUAL_EMBEDDINGS_LARGE_COLLECTION", "RAGDocument768")

        self.dual_store = DualCollectionVectorStore(
            client=self.client,
            small_collection_name=small_collection,
            large_collection_name=large_collection,
            small_embedding_dim=int(os.getenv("SMALL_EMBEDDING_DIM", "384")),
            large_embedding_dim=int(os.getenv("LARGE_EMBEDDING_DIM", "768")),
            importance_classifier=self.classifier,
            enable_multi_tenancy=settings.WEAVIATE_MULTI_TENANCY,
        )

        # CRITICAL: We need both 384 and 768 embedding services for re-embedding
        # The current implementation tries to copy vectors without re-embedding,
        # which will FAIL if dimensions don't match the target collection.

        # For dual embeddings, we need two separate model configurations
        # Expected env vars:
        # - LMSTUDIO_EMBEDDING_MODEL_768: e.g., "text-embedding-nomic-embed-text-v2-moe"
        #   (Recommended: Nomic Embed v2 MoE - best open-source embedding model)
        # - LMSTUDIO_EMBEDDING_MODEL_384: e.g., "sentence-transformers/all-MiniLM-L6-v2"

        model_768 = os.getenv("LMSTUDIO_EMBEDDING_MODEL_768", settings.EMBEDDING_MODEL)
        model_384 = os.getenv("LMSTUDIO_EMBEDDING_MODEL_384")

        if not model_384:
            log.error(
                "MIGRATION ABORTED: LMSTUDIO_EMBEDDING_MODEL_384 not set. "
                "Dual embedding migration requires two models configured. "
                "Please set LMSTUDIO_EMBEDDING_MODEL_384 to a 384-dim model "
                "(e.g., 'sentence-transformers/all-MiniLM-L6-v2') in your environment."
            )
            raise ValueError(
                "LMSTUDIO_EMBEDDING_MODEL_384 environment variable is required for dual embedding migration"
            )

        # Initialize 768-dim service with modified config if custom model specified
        # For dual embeddings, we need to temporarily override the embedding model setting
        # Save original value to restore later
        original_model = settings.EMBEDDING_MODEL

        # Initialize 768-dim service
        settings.EMBEDDING_MODEL = model_768
        provider_768 = ProviderFactory(settings)
        self.embedding_service_768 = get_embedding_service(settings, provider_768)

        # Initialize 384-dim service
        settings.EMBEDDING_MODEL = model_384
        provider_384 = ProviderFactory(settings)
        self.embedding_service_384 = get_embedding_service(settings, provider_384)

        # Restore original model setting
        settings.EMBEDDING_MODEL = original_model

        log.info(
            "Dual embedding services initialized: 768-dim=%s, 384-dim=%s",
            model_768, model_384
        )

        log.info(
            "DualEmbeddingMigrator initialized: source=%s, dry_run=%s",
            source_collection, dry_run
        )

    def analyze(self) -> Dict[str, Any]:
        """Analyze the source collection without migrating.

        Returns:
            Statistics about how documents would be classified
        """
        log.info("Analyzing source collection: %s", self.source_collection)

        try:
            collection = self.client.collections.get(self.source_collection)
            result = collection.aggregate.over_all(total_count=True)
            total_count = result.total_count if result else 0

            log.info("Total documents in source: %d", total_count)

            # Sample documents to classify
            sample_response = collection.query.fetch_objects(limit=min(total_count, 1000))
            sample_docs = sample_response.objects if hasattr(sample_response, "objects") else []

            # Classify samples
            high_count = 0
            low_count = 0

            for obj in sample_docs:
                source = obj.properties.get("source", "")
                importance = self.classifier.classify(source)

                if importance == ImportanceLevel.HIGH:
                    high_count += 1
                else:
                    low_count += 1

            # Extrapolate to full collection
            if sample_docs:
                high_pct = high_count / len(sample_docs)
                low_pct = low_count / len(sample_docs)

                estimated_high = int(total_count * high_pct)
                estimated_low = int(total_count * low_pct)
            else:
                estimated_high = 0
                estimated_low = 0
                high_pct = 0
                low_pct = 0

            stats = {
                "total_documents": total_count,
                "sample_size": len(sample_docs),
                "high_importance_count": high_count,
                "low_importance_count": low_count,
                "high_importance_pct": round(high_pct * 100, 2),
                "low_importance_pct": round(low_pct * 100, 2),
                "estimated_high_total": estimated_high,
                "estimated_low_total": estimated_low,
            }

            # Memory estimate
            # Assuming 4 bytes per float32 dimension
            current_mem_mb = (total_count * 768 * 4) / (1024 * 1024)
            new_mem_mb = (
                (estimated_high * 768 * 4) + (estimated_low * 384 * 4)
            ) / (1024 * 1024)
            savings_mb = current_mem_mb - new_mem_mb
            savings_pct = (savings_mb / current_mem_mb * 100) if current_mem_mb > 0 else 0

            stats["memory_estimate"] = {
                "current_mb": round(current_mem_mb, 2),
                "after_migration_mb": round(new_mem_mb, 2),
                "savings_mb": round(savings_mb, 2),
                "savings_pct": round(savings_pct, 2),
            }

            return stats

        except Exception as e:
            log.error("Analysis failed: %s", e, exc_info=True)
            return {"error": str(e)}

    def migrate(self, tenant: Optional[str] = None) -> Dict[str, Any]:
        """Perform the migration.

        Args:
            tenant: Optional tenant to migrate (if None, migrates all)

        Returns:
            Migration statistics
        """
        if self.dry_run:
            log.info("DRY RUN: Would migrate collection %s", self.source_collection)
            return self.analyze()

        log.info("Starting migration of collection: %s", self.source_collection)

        stats = {
            "migrated_high": 0,
            "migrated_low": 0,
            "failed": 0,
            "total_processed": 0,
        }

        try:
            collection = self.client.collections.get(self.source_collection)

            # Get all documents (paginated)
            offset = 0
            while True:
                response = collection.query.fetch_objects(
                    limit=self.batch_size,
                    offset=offset,
                )

                objects = response.objects if hasattr(response, "objects") else []
                if not objects:
                    break

                # Process batch
                for obj in tqdm(objects, desc=f"Migrating batch {offset}"):
                    try:
                        source = obj.properties.get("source", "")
                        importance = self.classifier.classify(source)

                        # Determine target collection
                        if importance == ImportanceLevel.HIGH:
                            target_collection = self.dual_store.large_collection_name
                            stats["migrated_high"] += 1
                        else:
                            target_collection = self.dual_store.small_collection_name
                            stats["migrated_low"] += 1

                        # Prepare chunk for insertion
                        text = obj.properties.get("text", "")
                        chunk = {
                            "text": text,
                            "source": source,
                            "chunk_index": obj.properties.get("chunk_index", 0),
                            "file_id": obj.properties.get("file_id", ""),
                            "file_path": obj.properties.get("file_path", ""),
                            "importance_level": importance.value,
                        }

                        # CRITICAL: Re-embed with correct dimensions for target collection
                        if importance == ImportanceLevel.HIGH:
                            # Use 768-dim embedding service
                            if self.embedding_service_768 and text:
                                chunk["vector"] = self.embedding_service_768.generate(text)
                            else:
                                log.error("Cannot migrate HIGH importance doc: no 768-dim service")
                                stats["failed"] += 1
                                continue
                        else:
                            # Use 384-dim embedding service
                            if self.embedding_service_384 and text:
                                chunk["vector"] = self.embedding_service_384.generate(text)
                            else:
                                log.error(
                                    "Cannot migrate LOW importance doc: no 384-dim service. "
                                    "Skipping document from %s", source
                                )
                                stats["failed"] += 1
                                continue

                        # Insert into target collection
                        self.dual_store.insert_batch(
                            collection_name=target_collection,
                            chunks=[chunk],
                            tenant=tenant,
                        )

                        stats["total_processed"] += 1

                    except Exception as e:
                        log.error("Failed to migrate document: %s", e)
                        stats["failed"] += 1

                offset += self.batch_size

                # Safety check to avoid infinite loop
                if offset > 100000:  # Adjust based on your collection size
                    log.warning("Reached offset limit, stopping migration")
                    break

            log.info(
                "Migration complete: processed=%d, high=%d, low=%d, failed=%d",
                stats["total_processed"],
                stats["migrated_high"],
                stats["migrated_low"],
                stats["failed"],
            )

            return stats

        except Exception as e:
            log.error("Migration failed: %s", e, exc_info=True)
            stats["error"] = str(e)
            return stats


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Migrate existing embeddings to dual-collection system"
    )
    parser.add_argument(
        "--source",
        default="RAGDocument768",
        help="Source collection name (default: RAGDocument768)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="Batch size for migration (default: 50)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze only, don't migrate",
    )
    parser.add_argument(
        "--tenant",
        help="Migrate specific tenant only",
    )

    args = parser.parse_args()

    # Create migrator
    migrator = DualEmbeddingMigrator(
        source_collection=args.source,
        batch_size=args.batch_size,
        dry_run=args.dry_run,
    )

    # Run analysis or migration
    if args.dry_run:
        print("\n=== ANALYSIS MODE ===")
        stats = migrator.analyze()
        print("\nResults:")
        import json
        print(json.dumps(stats, indent=2))
    else:
        print("\n=== MIGRATION MODE ===")
        print(f"Migrating collection: {args.source}")
        print(f"Batch size: {args.batch_size}")
        if args.tenant:
            print(f"Tenant: {args.tenant}")

        response = input("\nProceed with migration? (yes/no): ")
        if response.lower() != "yes":
            print("Migration cancelled")
            return

        stats = migrator.migrate(tenant=args.tenant)
        print("\nMigration Results:")
        import json
        print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
