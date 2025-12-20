#!/usr/bin/env python3
"""Quick test script for RAG query system."""
import sys

import pytest

from src.query.cli import create_rag_system
from src.rag.engine import AppConfig

pytestmark = pytest.mark.integration

def main():
    print("Testing RAG Query System\n")
    print("=" * 70)

    # Load config
    print("\n1) Loading configuration...")
    try:
        config = AppConfig()
        print(f"   OK Config loaded: Weaviate={config.WEAVIATE_URL}, LMStudio={config.OPENAI_API_BASE}")
    except Exception as e:
        print(f"   FAIL Failed to load config: {e}")
        return 1

    # Initialize RAG system
    print("\n2) Initializing RAG system...")
    try:
        rag = create_rag_system(config)
        print("   OK RAG system initialized")
    except Exception as e:
        print(f"   FAIL Failed to initialize RAG: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Test retriever
    print("\n3) Testing retriever...")
    try:
        stats = rag.retriever.get_stats()
        print(f"   OK Collection: {stats.get('collection')}")
        print(f"   OK Total documents: {stats.get('total_documents', 'N/A')}")
    except Exception as e:
        print(f"   WARN Stats failed: {e}")

    # Test query
    print("\n4) Testing query...")
    test_question = "What are the main topics in the ingested documents?"
    try:
        result = rag.query(question=test_question, top_k=3)

        print(f"\n   Question: {test_question}")
        print(f"\n   Answer:\n   {result['answer'][:200]}...")
        print(f"\n   Retrieved: {result['metadata']['retrieved_count']} documents")
        if result.get('sources'):
            print(f"   Sources: {len(result['sources'])} unique files")
            for i, src in enumerate(result['sources'][:3], 1):
                print(f"     {i}. {src['path']}")

        print("\n   OK Query test passed!")
    except Exception as e:
        print(f"   FAIL Query failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    print("\n" + "=" * 70)
    print("OK All tests passed! RAG system is working.\n")
    print("To use interactively, run:")
    print("  python -m src.query.cli\n")
    return 0


def test_rag_query_end_to_end():
    assert main() == 0

if __name__ == "__main__":
    sys.exit(main())
