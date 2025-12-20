"""Example using OpenAI SDK with the RAG API."""
import pytest

OpenAI = pytest.importorskip("openai").OpenAI

pytestmark = pytest.mark.integration


def main():
    """Example using OpenAI SDK."""

    # Configure client to point to your local RAG API
    client = OpenAI(
        base_url="http://localhost:8000/v1",
        api_key="not-needed"  # Your API doesn't require auth (yet)
    )

    print("\n" + "="*60)
    print("  OpenAI SDK with RAG API")
    print("="*60)

    # Example 1: List models
    print("\n1)  Listing available models...")
    print("-" * 60)
    models = client.models.list()
    for model in models.data:
        print(f"  - {model.id} (owned by: {model.owned_by})")

    # Example 2: Simple chat completion
    print("\n2)  Simple chat completion...")
    print("-" * 60)
    response = client.chat.completions.create(
        model="rag-local",
        messages=[
            {"role": "user", "content": "What is machine learning?"}
        ],
        temperature=0.7,
        max_tokens=300
    )

    answer = response.choices[0].message.content
    print(f"\nAnswer:\n{answer}\n")
    print(f"Usage: {response.usage.total_tokens} tokens")

    # Example 3: Conversation with context
    print("\n3)  Multi-turn conversation...")
    print("-" * 60)
    messages = [
        {"role": "system", "content": "You are a helpful AI tutor."},
        {"role": "user", "content": "Explain neural networks"},
        {"role": "assistant", "content": "Neural networks are..."},
        {"role": "user", "content": "How do they learn?"}
    ]

    response = client.chat.completions.create(
        model="rag-local",
        messages=messages,
        temperature=0.7
    )

    print(f"Answer:\n{response.choices[0].message.content}\n")

    # Example 4: Generate embeddings
    print("\n4)  Generating embeddings...")
    print("-" * 60)
    embedding_response = client.embeddings.create(
        model="text-embedding-ada-002",
        input="Hello, world!"
    )

    embedding = embedding_response.data[0].embedding
    print(f"OK Generated embedding with {len(embedding)} dimensions")
    print(f"First 5 values: {embedding[:5]}")

    # Example 5: Batch embeddings
    print("\n5)  Batch embeddings...")
    print("-" * 60)
    texts = [
        "Machine learning",
        "Deep learning",
        "Artificial intelligence"
    ]

    embedding_response = client.embeddings.create(
        model="text-embedding-ada-002",
        input=texts
    )

    print(f"OK Generated {len(embedding_response.data)} embeddings")
    for i, emb in enumerate(embedding_response.data):
        print(f"  {i+1}. Dimension: {len(emb.embedding)}")

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
        print("  2. OpenAI SDK is installed: pip install openai")
        print()


def test_openai_sdk_example():
    main()
