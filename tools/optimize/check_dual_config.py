#!/usr/bin/env python3
"""Simple configuration checker for dual embeddings without heavy dependencies."""

import os
import requests
from pathlib import Path


def load_env(env_path=".env"):
    """Load .env file into environment variables."""
    if not Path(env_path).exists():
        return

    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    # Remove inline comments
                    if '#' in value:
                        value = value.split('#')[0]
                    # Remove quotes if present
                    value = value.strip().strip('"').strip("'")
                    os.environ.setdefault(key, value)


def test_embedding_model(model_name, expected_dim):
    """Test if an embedding model is available and returns correct dimensions."""
    try:
        response = requests.post(
            "http://127.0.0.1:1234/v1/embeddings",
            json={"model": model_name, "input": "test"},
            timeout=5
        )

        if response.status_code == 200:
            data = response.json()
            embedding = data.get("data", [{}])[0].get("embedding", [])
            actual_dim = len(embedding)

            if actual_dim == expected_dim:
                return True, actual_dim, None
            else:
                return False, actual_dim, f"Dimension mismatch: {actual_dim} != {expected_dim}"
        else:
            return False, 0, f"HTTP {response.status_code}"

    except Exception as e:
        return False, 0, str(e)


def main():
    # Load .env
    load_env()

    print("━" * 78)
    print("[Left-Pointing Magnifying Glass] Dual Embeddings Configuration Check")
    print("━" * 78)
    print()

    # Get config
    enabled = os.getenv("ENABLE_DUAL_EMBEDDINGS", "false").lower() == "true"
    small_dim = int(os.getenv("SMALL_EMBEDDING_DIM", "384"))
    large_dim = int(os.getenv("LARGE_EMBEDDING_DIM", "768"))
    small_collection = os.getenv("DUAL_EMBEDDINGS_SMALL_COLLECTION", "RAGDocument384")
    large_collection = os.getenv("DUAL_EMBEDDINGS_LARGE_COLLECTION", "RAGDocument768")
    small_model = os.getenv("SMALL_EMBEDDING_MODEL", "text-embedding-bge-micro-v2")
    large_model = os.getenv("LARGE_EMBEDDING_MODEL", "text-embedding-nomic-embed-text-v2-moe")

    # Print config
    print("[Clipboard] Configuration:")
    print(f"  ├─ ENABLE_DUAL_EMBEDDINGS: {enabled}")
    print(f"  ├─ SMALL_EMBEDDING_DIM: {small_dim}")
    print(f"  ├─ LARGE_EMBEDDING_DIM: {large_dim}")
    print(f"  ├─ SMALL_COLLECTION: {small_collection}")
    print(f"  ├─ LARGE_COLLECTION: {large_collection}")
    print(f"  ├─ SMALL_MODEL: {small_model}")
    print(f"  └─ LARGE_MODEL: {large_model}")
    print()

    # Test models
    print("[Test Tube] Testing LM Studio models...")
    print()

    print(f"  Testing SMALL model ({small_model})...")
    success, dim, error = test_embedding_model(small_model, small_dim)
    if success:
        print(f"    ✓ Model OK: {dim} dimensions (matches config)")
    elif dim > 0:
        print(f"    ⚠️  Warning: {dim} dimensions (expected {small_dim})")
    else:
        print(f"    ✗ ERROR: {error}")

    print(f"  Testing LARGE model ({large_model})...")
    success, dim, error = test_embedding_model(large_model, large_dim)
    if success:
        print(f"    ✓ Model OK: {dim} dimensions (matches config)")
    elif dim > 0:
        print(f"    ⚠️  Warning: {dim} dimensions (expected {large_dim})")
    else:
        print(f"    ✗ ERROR: {error}")

    print()

    # Resource limits
    weaviate_mem = os.getenv("WEAVIATE_MEMORY", "8g")
    neo4j_mem = os.getenv("NEO4J_MEMORY", "3g")
    neo4j_heap = os.getenv("NEO4J_HEAP_MAX", "2G")
    redis_mem = os.getenv("REDIS_MEMORY", "1g")
    app_mem = os.getenv("APP_MEMORY", "3g")

    print("[Bar Chart] Resource Limits (from .env):")
    print(f"  ├─ WEAVIATE_MEMORY: {weaviate_mem}")
    print(f"  ├─ NEO4J_MEMORY: {neo4j_mem}")
    print(f"  ├─ NEO4J_HEAP_MAX: {neo4j_heap}")
    print(f"  ├─ REDIS_MEMORY: {redis_mem}")
    print(f"  └─ APP_MEMORY: {app_mem}")
    print()

    # Chunk config
    chunk_size = os.getenv("CHUNK_SIZE", "500")
    chunk_overlap = os.getenv("CHUNK_OVERLAP", "50")

    print("[Wrench] Chunk Configuration:")
    print(f"  ├─ CHUNK_SIZE: {chunk_size}")
    print(f"  └─ CHUNK_OVERLAP: {chunk_overlap}")
    print()

    # Summary
    if enabled:
        print("✓ Dual embeddings system is ENABLED and ready to use!")
        print()
        print("[Memo] Next steps:")
        print("  1. Restart containers: podman-compose down && podman-compose up -d")
        print("  2. Ingest documents (they'll auto-route to small/large collections)")
        print("  3. Monitor memory: podman stats")
    else:
        print("⚠️  Dual embeddings system is DISABLED")
        print()
        print("To enable:")
        print("  1. Edit .env and set: ENABLE_DUAL_EMBEDDINGS=true")
        print("  2. Run this script again to verify")

    print()
    print("━" * 78)


if __name__ == "__main__":
    main()
