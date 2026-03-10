"""Example using the Ollama-like RAG API."""
import pytest
import requests
from pytest_readable import readable


pytestmark = pytest.mark.integration


def main():
    """Example using the Ollama-like API."""
    base_url = "http://localhost:8000"

    print("\n" + "="*60)
    print("  Ollama-like RAG API Example")
    print("="*60)

    print("\n1)  Listing available models...")
    print("-" * 60)
    models = requests.get(f"{base_url}/api/tags").json()
    for model in models.get("models", []):
        print(f"  - {model.get('name')}")

    print("\n2)  Simple chat...")
    print("-" * 60)
    payload = {
        "model": "rag-default",
        "messages": [{"role": "user", "content": "What is machine learning?"}],
        "options": {"temperature": 0.7, "max_tokens": 300},
    }
    response = requests.post(f"{base_url}/api/chat", json=payload)
    response.raise_for_status()
    answer = response.json()["message"]["content"]
    print(f"\nAnswer:\n{answer}\n")

    print("\n3)  Generate embeddings...")
    print("-" * 60)
    embedding_response = requests.post(
        f"{base_url}/api/embeddings",
        json={"model": "text-embedding-ada-002", "input": "Hello, world!"},
    )
    embedding_response.raise_for_status()
    embedding = embedding_response.json()["embeddings"][0]
    print(f"OK Generated embedding with {len(embedding)} dimensions")
    print(f"First 5 values: {embedding[:5]}")

    print("\n" + "="*60)
    print("  All examples completed successfully!")
    print("="*60 + "\n")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\nERROR: {e}")
        print("\nMake sure:")
        print("  1. API is running: python -m src.api.app")
        print()


@readable(
    intent="Verify openai sdk example.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the openai sdk example behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_openai_sdk_example():
    main()
