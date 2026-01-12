"""CLI for querying the RAG system."""
import argparse
import sys

from src.api.runtime import RuntimeFactory
from src.workflows.query.engine import AppConfig
from src.workflows.query.pipeline.rag_orchestrator import RAGOrchestrator
from src.workflows.query.audit import get_logger

log = get_logger(__name__)




def interactive_mode(rag: RAGOrchestrator):
    """Run interactive query session.

    Args:
        rag: RAG orchestrator instance.
    """
    print("\n===================================================================")
    print("RAG Interactive Query System")
    print("Type your questions below. Type 'exit' or 'quit' to end")
    print("===================================================================\n")

    while True:
        try:
            # Get user input with explicit UTF-8 encoding handling
            question = input("\nYour question: ").strip()
            # Clean any surrogate characters that might have been introduced
            question = question.encode('utf-8', errors='surrogatepass').decode('utf-8', errors='ignore')

            if not question:
                continue

            if question.lower() in ["exit", "quit", "q"]:
                print("\nGoodbye!")
                break

            # Execute RAG query
            print("\nSearching and generating answer...\n")
            result = rag.query(question=question, top_k=5, temperature=0.7)

            # Display answer
            print("=" * 70)
            print(f"Answer:\n\n{result['answer']}")
            print("=" * 70)

            # Display sources
            if result.get("sources"):
                print(f"\nSources ({len(result['sources'])} documents):")
                for i, source in enumerate(result["sources"], 1):
                    print(f"  {i}. {source['path']} (score: {source['relevance_score']:.3f})")

            # Display metadata
            metadata = result.get("metadata", {})
            print(f"\nRetrieved: {metadata.get('retrieved_count', 0)} chunks")

        except KeyboardInterrupt:
            print("\n\nInterrupted. Goodbye!")
            break
        except Exception as e:
            log.error("Query failed: %s", e)
            print(f"\nError: {e}\n")


def single_query_mode(rag: RAGOrchestrator, question: str, top_k: int = 5):
    """Execute a single query and exit.

    Args:
        rag: RAG orchestrator instance.
        question: Question to ask.
        top_k: Number of documents to retrieve.
    """
    print(f"\nQuestion: {question}\n")
    print("Searching and generating answer...\n")

    try:
        result = rag.query(question=question, top_k=top_k, temperature=0.7)

        # Display answer
        print("=" * 70)
        print(f"Answer:\n\n{result['answer']}")
        print("=" * 70)

        # Display sources
        if result.get("sources"):
            print(f"\nSources ({len(result['sources'])} documents):")
            for i, source in enumerate(result["sources"], 1):
                print(f"  {i}. {source['path']} (score: {source['relevance_score']:.3f})")

        # Display metadata
        metadata = result.get("metadata", {})
        print(f"\nRetrieved: {metadata.get('retrieved_count', 0)} chunks\n")

    except Exception as e:
        log.error("Query failed: %s", e)
        print(f"\nError: {e}\n")
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

  # Single query (positional)
  python -m src.query.cli "What is the main topic of the documents?"

  # Retrieve more documents
  python -m src.query.cli "Explain the architecture" --top-k 10
        """,
    )

    parser.add_argument(
        "query",
        nargs="*",
        help="Query text (if omitted, enters interactive mode)"
    )

    parser.add_argument(
        "--question", "-q",
        type=str,
        help="Deprecated: use the positional query text instead"
    )

    parser.add_argument(
        "--top-k", "-k",
        type=int,
        default=5,
        help="Number of documents to retrieve (default: 5)"
    )

    args = parser.parse_args()

    if args.question and args.query:
        print("Provide either a positional query or --question, not both.")
        sys.exit(2)

    question = args.question or (" ".join(args.query).strip() if args.query else None)

    # Load configuration
    try:
        config = AppConfig()
        log.info("Configuration loaded successfully")
    except Exception as e:
        print(f"Failed to load configuration: {e}")
        sys.exit(1)

    factory = RuntimeFactory(config, rag_overrides={"enable_rag_gating": False})

    try:
        with factory.context() as resources:
            rag = resources.rag_orchestrator
            if question:
                single_query_mode(rag, question, args.top_k)
            else:
                interactive_mode(rag)
    except Exception as e:
        print(f"Failed to initialize RAG system: {e}")
        log.error("RAG initialization failed", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
