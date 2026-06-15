"""Example script to test the Ollama-like RAG API endpoints."""
import pytest
import requests
import json
from pytest_readable import readable



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


@readable(
    intent="Test health check endpoint.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the health behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_health():
    """Test health check endpoint."""
    print("\nTesting Health Check...")
    response = requests.get(f"{BASE_URL}/health")
    print_json(response.json(), "Health Check")
    assert response.status_code == 200
    return True


@readable(
    intent="Test tags listing endpoint.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the tags behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_tags():
    """Test tags listing endpoint."""
    print("\nTesting GET /api/tags...")
    response = requests.get(f"{BASE_URL}/api/tags")
    print_json(response.json(), "Available Models")
    assert response.status_code == 200
    return True


@readable(
    intent="Test chat endpoint.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the chat behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_chat():
    """Test chat endpoint."""
    print("\nTesting POST /api/chat...")
    payload = {
        "model": "rag-default",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "What is machine learning?"},
        ],
        "options": {"temperature": 0.7, "max_tokens": 512, "top_k": 5},
    }

    response = requests.post(
        f"{BASE_URL}/api/chat",
        json=payload,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    print_json(data, "Chat Response")
    answer = data["message"]["content"]
    print(f"Answer Preview:\n{answer[:200]}...\n")
    return True


@readable(
    intent="Test generate endpoint.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the generate behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_generate():
    """Test generate endpoint."""
    print("\nTesting POST /api/generate...")
    payload = {
        "model": "rag-default",
        "prompt": "Explain neural networks in simple terms",
        "system": "You are a concise assistant.",
        "options": {"temperature": 0.7, "max_tokens": 512, "top_k": 3},
    }

    response = requests.post(
        f"{BASE_URL}/api/generate",
        json=payload,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    print_json(data, "Generate Response")
    return True


@readable(
    intent="Test embeddings endpoint.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the embeddings behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_embeddings():
    """Test embeddings endpoint."""
    print("\nTesting POST /api/embeddings...")
    payload = {"model": "text-embedding-ada-002", "input": "Hello world"}

    response = requests.post(
        f"{BASE_URL}/api/embeddings",
        json=payload,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    embedding = data["embeddings"][0]
    print("\nEmbedding Generated!")
    print(f"  - Model: {data['model']}")
    print(f"  - Dimension: {len(embedding)}")
    print(f"  - First 10 values: {embedding[:10]}")
    return True


@readable(
    intent="Test RAG query endpoint.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the rag query behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_rag_query():
    """Test RAG query endpoint."""
    print("\nTesting POST /rag/query...")
    payload = {"query": "What is machine learning?", "top_k": 3}

    response = requests.post(
        f"{BASE_URL}/rag/query",
        json=payload,
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    print_json(data, "RAG Query Response")
    return True


def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("  RAG API Test Suite (Ollama-like)")
    print("="*60)
    print(f"\nBase URL: {BASE_URL}")
    print("\nMake sure the API is running:")
    print("  python -m src.api.app")
    print("\n" + "-"*60)

    results = {
        "Health Check": test_health(),
        "Tags": test_tags(),
        "Chat": test_chat(),
        "Generate": test_generate(),
        "Embeddings": test_embeddings(),
        "RAG Query": test_rag_query(),
    }

    print("\n" + "="*60)
    print("  Test Summary")
    print("="*60)

    for test_name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"{status} - {test_name}")

    total = len(results)
    passed = sum(results.values())
    print(f"\nTotal: {passed}/{total} tests passed")
    print("="*60 + "\n")


if __name__ == "__main__":
    try:
        main()
    except requests.exceptions.ConnectionError:
        print("\nERROR: Could not connect to API!")
        print(f"Make sure the API is running at {BASE_URL}")
        print("\nStart it with:")
        print("  python -m src.api.app")
        print()
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
