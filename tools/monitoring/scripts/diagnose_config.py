#!/usr/bin/env python3
"""
Configuration Diagnostic Script

This script verifies that all critical configurations are correct for the RAG ingestion pipeline.
It checks:
1. Redis connectivity for embedding cache
2. Redis connectivity for PDF cache
3. Embedding dimension configuration
4. LM Studio connectivity and available models
5. Weaviate connectivity and schema
"""

import os
import sys
import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

pytestmark = pytest.mark.integration

def check_redis_connection():
    """Check Redis connectivity."""
    print("\n" + "="*60)
    print("CHECKING REDIS CONNECTIVITY")
    print("="*60)

    try:
        import redis

        redis_host = os.environ.get("REDIS_HOST", "127.0.0.1")
        redis_port = int(os.environ.get("REDIS_PORT", 6379))
        redis_password = (os.environ.get("REDIS_PASSWORD") or "").strip() or None

        print(f"Connecting to Redis at {redis_host}:{redis_port}...")

        client = redis.Redis(
            host=redis_host,
            port=redis_port,
            db=0,
            decode_responses=False,
            socket_connect_timeout=2,
            socket_timeout=2,
            password=redis_password,
        )

        # Test connection
        client.ping()
        print("Redis connection successful")

        # Check cache keys
        embed_keys = len(client.keys("embed:*"))
        pdf_keys = len(client.keys("pdf_content:*"))

        print(f"   - Embedding cache keys: {embed_keys}")
        print(f"   - PDF cache keys: {pdf_keys}")

        return True

    except ImportError:
        print("ERROR: redis-py not installed")
        return False
    except Exception as e:
        print(f"ERROR: Redis connection failed: {e}")
        return False


def check_embedding_config():
    """Check embedding dimension configuration."""
    print("\n" + "="*60)
    print("CHECKING EMBEDDING CONFIGURATION")
    print("="*60)

    try:
        from src.rag.conf import Config

        config = Config()

        embedding_backend = getattr(config, "EMBEDDING_BACKEND", None)
        embedding_dim = getattr(config, "EMBEDDING_DIM", None)
        embedding_model = getattr(config, "EMBEDDING_MODEL", None)
        embedding_max_tokens = getattr(config, "EMBEDDING_MAX_TOKENS", None)

        print(f"Configuration loaded:")
        print(f"   - EMBEDDING_BACKEND: {embedding_backend}")
        print(f"   - EMBEDDING_DIM: {embedding_dim}")
        print(f"   - EMBEDDING_MODEL: {embedding_model}")
        print(f"   - EMBEDDING_MAX_TOKENS: {embedding_max_tokens}")

        # Check if dimension matches expected models
        if embedding_dim == 768:
            print("EMBEDDING_DIM=768 (compatible with nomic-embed models)")
        elif embedding_dim == 384:
            print("WARNING: EMBEDDING_DIM=384 (compatible with minilm models)")
            print("   Note: Ensure you're using a 384-dim model like all-minilm-l6-v2")
        else:
            print(f"WARNING: EMBEDDING_DIM={embedding_dim} (non-standard dimension)")

        return True

    except Exception as e:
        print(f"ERROR: Failed to load config: {e}")
        return False


def check_lmstudio_connectivity():
    """Check LM Studio connectivity and list models."""
    print("\n" + "="*60)
    print("CHECKING LM STUDIO CONNECTIVITY")
    print("="*60)

    try:
        import requests

        lm_host = os.environ.get("LMSTUDIO_HOST", "127.0.0.1")
        lm_port = os.environ.get("LMSTUDIO_PORT", "1234")
        base_url = f"http://{lm_host}:{lm_port}"

        print(f"Connecting to LM Studio at {base_url}...")

        # Get models list
        response = requests.get(f"{base_url}/v1/models", timeout=5)
        response.raise_for_status()

        models = response.json().get("data", [])

        print("LM Studio connected successfully")
        print(f"   - Available models: {len(models)}")

        # Separate embedding and LLM models
        embed_models = [m for m in models if "embedding" in m.get("id", "").lower()]
        llm_models = [m for m in models if "embedding" not in m.get("id", "").lower()]

        print(f"\n   Embedding models ({len(embed_models)}):")
        for model in embed_models:
            print(f"      - {model.get('id', 'unknown')}")

        print(f"\n   LLM models ({len(llm_models)}):")
        for model in llm_models[:5]:  # Show first 5
            print(f"      - {model.get('id', 'unknown')}")
        if len(llm_models) > 5:
            print(f"      ... and {len(llm_models) - 5} more")

        return True

    except ImportError:
        print("ERROR: requests library not installed")
        return False
    except requests.exceptions.ConnectionError:
        print(f"ERROR: Cannot connect to LM Studio at {base_url}")
        print("   Make sure LM Studio is running and accessible")
        return False
    except Exception as e:
        print(f"ERROR: LM Studio connectivity check failed: {e}")
        return False


def check_weaviate_connectivity():
    """Check Weaviate connectivity and schema."""
    print("\n" + "="*60)
    print("CHECKING WEAVIATE CONNECTIVITY")
    print("="*60)

    try:
        import requests

        weaviate_url = os.environ.get("WEAVIATE_URL", "http://weaviate:8080")
        # If using service name, try localhost for direct access
        if "weaviate:" in weaviate_url:
            weaviate_url_test = weaviate_url.replace("weaviate:", "127.0.0.1:")
        else:
            weaviate_url_test = weaviate_url

        print(f"Connecting to Weaviate at {weaviate_url_test}...")

        # Get schema
        response = requests.get(f"{weaviate_url_test}/v1/schema", timeout=5)
        response.raise_for_status()

        schema = response.json()
        classes = schema.get("classes", [])

        print("Weaviate connected successfully")
        print(f"   - Classes defined: {len(classes)}")

        # Check RAGDocument class
        rag_class = next((c for c in classes if c.get("class") == "RAGDocument"), None)
        if rag_class:
            vector_config = rag_class.get("vectorizer", {})
            properties = rag_class.get("properties", [])

            print(f"\n   RAGDocument class found:")
            print(f"      - Properties: {len(properties)}")
            print(f"      - Vectorizer: {rag_class.get('vectorizer', 'none')}")

            # Check vector index config
            vector_index = rag_class.get("vectorIndexConfig", {})
            if vector_index:
                print(f"      - Vector index type: {vector_index.get('type', 'unknown')}")
        else:
            print("\n   WARNING: RAGDocument class not found in schema")
            print("      This is normal if you have not run ingestion yet")

        return True

    except requests.exceptions.ConnectionError:
        print(f"ERROR: Cannot connect to Weaviate at {weaviate_url_test}")
        print("   Make sure Weaviate container is running")
        return False
    except Exception as e:
        print(f"ERROR: Weaviate connectivity check failed: {e}")
        return False


def check_environment_variables():
    """Check critical environment variables."""
    print("\n" + "="*60)
    print("CHECKING ENVIRONMENT VARIABLES")
    print("="*60)

    critical_vars = {
        "REDIS_HOST": "127.0.0.1",
        "REDIS_PORT": "6379",
        "WEAVIATE_URL": "http://weaviate:8080",
        "LMSTUDIO_HOST": "127.0.0.1",
        "RAG_EMBED_CACHE_ENABLED": "true",
        "RAG_PDF_CACHE_ENABLED": "true",
        "RAG_PIPELINE_WORKERS": "8",
    }

    for var, default in critical_vars.items():
        value = os.environ.get(var, default)
        if value:
            status = "OK"
        else:
            status = "WARNING"
        print(f"   {status}: {var}={value}")

    return True


def main():
    """Run all diagnostic checks."""
    print("\n" + "RAG INGESTION PIPELINE DIAGNOSTIC REPORT".center(60))
    print("=" * 60)

    results = {
        "Redis": check_redis_connection(),
        "Embedding Config": check_embedding_config(),
        "LM Studio": check_lmstudio_connectivity(),
        "Weaviate": check_weaviate_connectivity(),
        "Environment": check_environment_variables(),
    }

    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)

    for check, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"   {status}: {check}")

    all_passed = all(results.values())

    print("\n" + "="*60)
    if all_passed:
        print("ALL CHECKS PASSED - system ready for ingestion")
    else:
        print("SOME CHECKS FAILED - review errors above")
    print("="*60 + "\n")

    return 0 if all_passed else 1


def test_diagnose_config_checks():
    assert check_environment_variables()
    assert check_embedding_config()
    assert check_redis_connection()
    assert check_lmstudio_connectivity()
    assert check_weaviate_connectivity()


if __name__ == "__main__":
    sys.exit(main())
