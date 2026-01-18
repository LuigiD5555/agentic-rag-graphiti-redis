#!/usr/bin/env python3
"""Wrapper for ingestion that automatically uses dual embeddings when enabled.

This script:
1. Checks if ENABLE_DUAL_EMBEDDINGS=true
2. Classifies documents by importance
3. Routes to appropriate collection (small or large)
4. Handles embedding with correct model per collection
"""

import os
import sys
from pathlib import Path
from typing import List, Dict, Any

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import weaviate
import src.settings as settings
from src.workflows.query.importance import DocumentImportanceClassifier, ImportanceLevel
from src.backends.storage.vector.dual_store import DualCollectionVectorStore
from src.workflows.query.audit import get_logger

log = get_logger(__name__)


def get_dual_config() -> Dict[str, Any]:
    """Get dual embedding configuration from environment."""
    return {
        "enabled": os.getenv("ENABLE_DUAL_EMBEDDINGS", "false").lower() == "true",
        "small_dim": int(os.getenv("SMALL_EMBEDDING_DIM", "384")),
        "large_dim": int(os.getenv("LARGE_EMBEDDING_DIM", "768")),
        "small_collection": os.getenv("DUAL_EMBEDDINGS_SMALL_COLLECTION", "RAGDocument384"),
        "large_collection": os.getenv("DUAL_EMBEDDINGS_LARGE_COLLECTION", "RAGDocument768"),
        "small_model": os.getenv("SMALL_EMBEDDING_MODEL", "text-embedding-bge-micro-v2"),
        "large_model": os.getenv("LARGE_EMBEDDING_MODEL", "text-embedding-nomic-embed-text-v2-moe"),
    }


def setup_dual_collections() -> bool:
    """Setup dual collections in Weaviate if enabled.

    Returns:
        True if dual system is active, False otherwise
    """
    dual_config = get_dual_config()

    if not dual_config["enabled"]:
        log.info("Dual embeddings DISABLED, using standard single collection")
        return False

    log.info("Dual embeddings ENABLED, setting up collections...")

    try:
        # Create Weaviate client
        host = settings.WEAVIATE_URL.replace("http://", "").replace("https://", "").split(":")[0]
        port = int(settings.WEAVIATE_URL.split(":")[-1]) if ":" in settings.WEAVIATE_URL else 8080
        client = weaviate.connect_to_local(
            host=host,
            port=port,
            grpc_port=settings.WEAVIATE_GRPC_PORT,
        )

        classifier = DocumentImportanceClassifier()

        dual_store = DualCollectionVectorStore(
            client=client,
            small_collection_name=dual_config["small_collection"],
            large_collection_name=dual_config["large_collection"],
            small_embedding_dim=dual_config["small_dim"],
            large_embedding_dim=dual_config["large_dim"],
            importance_classifier=classifier,
            enable_multi_tenancy=settings.WEAVIATE_MULTI_TENANCY,
        )

        # Get stats to verify setup
        stats = dual_store.get_statistics()

        log.info("Dual collections ready:")
        log.info("  - Small (%s): %d docs, %d dims",
                 dual_config["small_collection"],
                 stats.get(dual_config["small_collection"], {}).get("total_documents", 0),
                 dual_config["small_dim"])
        log.info("  - Large (%s): %d docs, %d dims",
                 dual_config["large_collection"],
                 stats.get(dual_config["large_collection"], {}).get("total_documents", 0),
                 dual_config["large_dim"])

        if "memory_estimate" in stats:
            mem = stats["memory_estimate"]
            log.info("  - Memory savings: %.1f MB (%.1f%%)",
                     mem.get("savings_mb", 0),
                     mem.get("savings_percentage", 0))

        return True

    except Exception as e:
        log.error("Failed to setup dual collections: %s", e, exc_info=True)
        log.warning("Falling back to single collection mode")
        return False


def print_ingestion_plan(files: List[str], classifier: DocumentImportanceClassifier):
    """Print ingestion plan showing how files will be classified."""
    stats = classifier.get_statistics(files)

    print("\n" + "="*70)
    print("[Bar Chart] DUAL EMBEDDING INGESTION PLAN")
    print("="*70)
    print(f"\nTotal files to ingest: {stats['total_files']}")
    print(f"\n[Sparkles] HIGH importance (768 dims): {stats['high_importance']} files ({stats['high_percentage']:.1f}%)")
    print(f"   → Code, docs, configs, technical content")
    print(f"\n[Page Facing Up] LOW importance (384 dims): {stats['low_importance']} files ({stats['low_percentage']:.1f}%)")
    print(f"   → Logs, data, general text files")

    dual_config = get_dual_config()
    print(f"\n[Wrench] Models:")
    print(f"   - Small: {dual_config['small_model']} ({dual_config['small_dim']} dims)")
    print(f"   - Large: {dual_config['large_model']} ({dual_config['large_dim']} dims)")

    print("\n" + "="*70 + "\n")


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Check dual embeddings configuration and setup"
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify dual collections are set up correctly",
    )
    parser.add_argument(
        "--analyze-path",
        help="Analyze files in a path to see how they'd be classified",
    )

    args = parser.parse_args()

    dual_config = get_dual_config()

    # Print config
    print("\n[Left-Pointing Magnifying Glass] Dual Embeddings Configuration:")
    print(f"  Enabled: {dual_config['enabled']}")
    print(f"  Small collection: {dual_config['small_collection']} ({dual_config['small_dim']} dims)")
    print(f"  Large collection: {dual_config['large_collection']} ({dual_config['large_dim']} dims)")
    print(f"  Small model: {dual_config['small_model']}")
    print(f"  Large model: {dual_config['large_model']}")

    if not dual_config['enabled']:
        print("\n⚠️  Dual embeddings are DISABLED")
        print("   To enable, set ENABLE_DUAL_EMBEDDINGS=true in .env")
        return

    # Verify setup
    if args.verify or not args.analyze_path:
        print("\n[Wrench] Verifying dual collections setup...")
        is_ready = setup_dual_collections()

        if is_ready:
            print("✓ Dual embeddings system is ready!")
        else:
            print("✗ Dual embeddings system failed to initialize")
            sys.exit(1)

    # Analyze path if provided
    if args.analyze_path:
        from pathlib import Path
        import glob

        path = Path(args.analyze_path)
        if not path.exists():
            print(f"\n✗ Path not found: {path}")
            sys.exit(1)

        # Find all files recursively
        if path.is_file():
            files = [str(path)]
        else:
            files = [str(f) for f in path.rglob("*") if f.is_file()]

        if not files:
            print(f"\n✗ No files found in: {path}")
            sys.exit(1)

        # Classify and print plan
        classifier = DocumentImportanceClassifier()
        print_ingestion_plan(files[:100], classifier)  # Limit to first 100 for preview

        if len(files) > 100:
            print(f"(Showing preview of first 100 files, total: {len(files)})\n")


if __name__ == "__main__":
    main()
