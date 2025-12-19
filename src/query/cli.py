"""CLI for querying the RAG system."""
import argparse
import sys
import weaviate
from src.rag.engine import AppConfig
from src.rag.retrieval import WeaviateRetriever
from src.rag.chat import LMStudioChatService
from src.rag.pipeline.rag_orchestrator import RAGOrchestrator
from src.rag.audit import get_logger

log = get_logger(__name__)


def create_rag_system(config: AppConfig) -> RAGOrchestrator:
    """Create and initialize the RAG system.

    Args:
        config: Application configuration.

    Returns:
        Initialized RAG orchestrator.
    """
    # Initialize Weaviate client
    log.info("Connecting to Weaviate at %s", config.WEAVIATE_URL)
    weaviate_client = weaviate.connect_to_local(
        host=config.WEAVIATE_URL.replace("http://", "").replace("https://", "").split(":")[0],
        port=int(config.WEAVIATE_URL.split(":")[-1]) if ":" in config.WEAVIATE_URL else 8080,
        grpc_port=config.WEAVIATE_GRPC_PORT,
    )

    # Create retriever
    retriever = WeaviateRetriever(
        client=weaviate_client,
        collection_name=config.WEAVIATE_CLASS,
        tenant=config.WEAVIATE_DEFAULT_TENANT,
        top_k=5,  # Default number of results
    )

    # Create chat service
    chat_service = LMStudioChatService(
        base_url=config.OPENAI_API_BASE,
        api_key=config.OPENAI_API_KEY,
    )

    # Create RAG orchestrator
    rag = RAGOrchestrator(
        retriever=retriever,
        chat_service=chat_service,
        include_sources=True,
    )

    log.info("RAG system initialized successfully")
    return rag


def interactive_mode(rag: RAGOrchestrator):
    """Run interactive query session.

    Args:
        rag: RAG orchestrator instance.
    """
    print("\n╔═══════════════════════════════════════════════════════════╗")
    print("║          RAG Interactive Query System                     ║")
    print("║  Type your questions below. Type 'exit' or 'quit' to end  ║")
    print("╚═══════════════════════════════════════════════════════════╝\n")

    while True:
        try:
            # Get user input
            question = input("\n❓ Your question: ").strip()

            if not question:
                continue

            if question.lower() in ["exit", "quit", "q"]:
                print("\n👋 Goodbye!")
                break

            # Execute RAG query
            print("\n🔍 Searching and generating answer...\n")
            result = rag.query(question=question, top_k=5, temperature=0.7)

            # Display answer
            print("═" * 70)
            print(f"✅ Answer:\n\n{result['answer']}")
            print("═" * 70)

            # Display sources
            if result.get("sources"):
                print(f"\n📚 Sources ({len(result['sources'])} documents):")
                for i, source in enumerate(result["sources"], 1):
                    print(f"  {i}. {source['path']} (score: {source['relevance_score']:.3f})")

            # Display metadata
            metadata = result.get("metadata", {})
            print(f"\n📊 Retrieved: {metadata.get('retrieved_count', 0)} chunks")

        except KeyboardInterrupt:
            print("\n\n👋 Interrupted. Goodbye!")
            break
        except Exception as e:
            log.error("Query failed: %s", e)
            print(f"\n❌ Error: {e}\n")


def single_query_mode(rag: RAGOrchestrator, question: str, top_k: int = 5):
    """Execute a single query and exit.

    Args:
        rag: RAG orchestrator instance.
        question: Question to ask.
        top_k: Number of documents to retrieve.
    """
    print(f"\n❓ Question: {question}\n")
    print("🔍 Searching and generating answer...\n")

    try:
        result = rag.query(question=question, top_k=top_k, temperature=0.7)

        # Display answer
        print("═" * 70)
        print(f"✅ Answer:\n\n{result['answer']}")
        print("═" * 70)

        # Display sources
        if result.get("sources"):
            print(f"\n📚 Sources ({len(result['sources'])} documents):")
            for i, source in enumerate(result["sources"], 1):
                print(f"  {i}. {source['path']} (score: {source['relevance_score']:.3f})")

        # Display metadata
        metadata = result.get("metadata", {})
        print(f"\n📊 Retrieved: {metadata.get('retrieved_count', 0)} chunks\n")

    except Exception as e:
        log.error("Query failed: %s", e)
        print(f"\n❌ Error: {e}\n")
        sys.exit(1)


def main():
    """Main entry point for query CLI."""
    parser = argparse.ArgumentParser(
        description="Query the RAG system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode
  python -m src.query.cli

  # Single question
  python -m src.query.cli --question "What is the main topic of the documents?"

  # Retrieve more documents
  python -m src.query.cli --question "Explain the architecture" --top-k 10
        """,
    )

    parser.add_argument(
        "--question", "-q",
        type=str,
        help="Question to ask (if not provided, enters interactive mode)"
    )

    parser.add_argument(
        "--top-k", "-k",
        type=int,
        default=5,
        help="Number of documents to retrieve (default: 5)"
    )

    args = parser.parse_args()

    # Load configuration
    try:
        config = AppConfig()
        log.info("Configuration loaded successfully")
    except Exception as e:
        print(f"❌ Failed to load configuration: {e}")
        sys.exit(1)

    # Initialize RAG system
    try:
        rag = create_rag_system(config)
    except Exception as e:
        print(f"❌ Failed to initialize RAG system: {e}")
        log.error("RAG initialization failed", exc_info=True)
        sys.exit(1)

    # Run in appropriate mode
    if args.question:
        single_query_mode(rag, args.question, args.top_k)
    else:
        interactive_mode(rag)


if __name__ == "__main__":
    main()
