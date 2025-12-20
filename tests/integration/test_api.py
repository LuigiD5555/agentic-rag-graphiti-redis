"""Example script to test the RAG API endpoints."""
import pytest
import requests
import json


BASE_URL = "http://localhost:8000"

pytestmark = pytest.mark.integration


def print_json(data, title=""):
    """Pretty print JSON data."""
    if title:
        print(f"\n{'='*60}")
        print(f"  {title}")
        print('='*60)
    print(json.dumps(data, indent=2, ensure_ascii=False))
    print()


def test_health():
    """Test health check endpoint."""
    print("\n🔍 Testing Health Check...")
    response = requests.get(f"{BASE_URL}/health")
    print_json(response.json(), "Health Check")
    assert response.status_code == 200
    return True


def test_models():
    """Test models listing endpoint."""
    print("\n🔍 Testing GET /v1/models...")
    response = requests.get(f"{BASE_URL}/v1/models")
    print_json(response.json(), "Available Models")
    assert response.status_code == 200
    return True


def test_chat_completions():
    """Test chat completions endpoint."""
    print("\n🔍 Testing POST /v1/chat/completions...")

    payload = {
        "model": "rag-local",
        "messages": [
            {
                "role": "system",
                "content": "You are a helpful assistant."
            },
            {
                "role": "user",
                "content": "What is machine learning?"
            }
        ],
        "temperature": 0.7,
        "max_tokens": 512,
        "top_k": 5
    }

    response = requests.post(
        f"{BASE_URL}/v1/chat/completions",
        json=payload,
        headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 200, response.text
    data = response.json()
    print_json(data, "Chat Completion Response")

    # Extract and display just the answer
    answer = data["choices"][0]["message"]["content"]
    print(f"📝 Answer Preview:\n{answer[:200]}...\n")
    return True


def test_responses():
    """Test modern responses endpoint."""
    print("\n🔍 Testing POST /v1/responses...")

    payload = {
        "model": "rag-local",
        "input": "Explain neural networks in simple terms",
        "temperature": 0.7,
        "max_tokens": 512,
        "top_k": 3
    }

    response = requests.post(
        f"{BASE_URL}/v1/responses",
        json=payload,
        headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 200, response.text
    data = response.json()
    print_json(data, "Response Object")

    # Display metadata
    metadata = data.get("metadata", {})
    print(f"\n📊 Metadata:")
    print(f"  - Retrieved: {metadata.get('retrieved_count', 0)} documents")
    print(f"  - Sources: {len(metadata.get('sources', []))}")
    if metadata.get("sources"):
        print(f"\n📚 Top Sources:")
        for src in metadata["sources"][:3]:
            print(f"  - {src['path']} (score: {src['relevance_score']:.3f})")
    return True


def test_embeddings():
    """Test embeddings endpoint."""
    print("\n🔍 Testing POST /v1/embeddings...")

    payload = {
        "model": "text-embedding-ada-002",
        "input": "Hello world"
    }

    response = requests.post(
        f"{BASE_URL}/v1/embeddings",
        json=payload,
        headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 200, response.text
    data = response.json()

    # Don't print full embedding (too long)
    embedding = data["data"][0]["embedding"]
    print(f"\n✅ Embedding Generated!")
    print(f"  - Model: {data['model']}")
    print(f"  - Dimension: {len(embedding)}")
    print(f"  - First 10 values: {embedding[:10]}")
    print(f"  - Usage: {data['usage']}")
    return True


def test_embeddings_batch():
    """Test embeddings with multiple inputs."""
    print("\n🔍 Testing POST /v1/embeddings (batch)...")

    payload = {
        "model": "text-embedding-ada-002",
        "input": [
            "Machine learning is fascinating",
            "Deep learning uses neural networks",
            "AI is transforming technology"
        ]
    }

    response = requests.post(
        f"{BASE_URL}/v1/embeddings",
        json=payload,
        headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 200, response.text
    data = response.json()
    print(f"\n✅ Batch Embeddings Generated!")
    print(f"  - Model: {data['model']}")
    print(f"  - Count: {len(data['data'])}")
    print(f"  - Dimension: {len(data['data'][0]['embedding'])}")
    print(f"  - Total tokens: {data['usage']['total_tokens']}")
    return True


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("  RAG API Test Suite")
    print("="*60)
    print(f"\nBase URL: {BASE_URL}")
    print("\nMake sure the API is running:")
    print("  python -m src.api.app")
    print("\n" + "-"*60)

    results = {
        "Health Check": test_health(),
        "Models": test_models(),
        "Chat Completions": test_chat_completions(),
        "Responses": test_responses(),
        "Embeddings": test_embeddings(),
        "Embeddings (Batch)": test_embeddings_batch(),
    }

    # Summary
    print("\n" + "="*60)
    print("  Test Summary")
    print("="*60)

    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {test_name}")

    total = len(results)
    passed = sum(results.values())
    print(f"\nTotal: {passed}/{total} tests passed")
    print("="*60 + "\n")


if __name__ == "__main__":
    try:
        main()
    except requests.exceptions.ConnectionError:
        print("\n❌ ERROR: Could not connect to API!")
        print(f"Make sure the API is running at {BASE_URL}")
        print("\nStart it with:")
        print("  python -m src.api.app")
        print()
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
