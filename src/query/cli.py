"""CLI for querying the RAG system."""
import argparse
import sys
import weaviate
from src.rag.engine import AppConfig
from src.rag.retrieval import WeaviateRetriever
from src.rag.chat import LMStudioChatService
from src.rag.pipeline.rag_orchestrator import RAGOrchestrator
from src.rag.audit import get_logger
from src.providers.lmstudio.embeddings import EmbeddingService
from src.providers.lmstudio.model_manager import ModelManager

log = get_logger(__name__)


class EmbeddingWeaviateRetriever:
    """Wrapper around WeaviateRetriever that handles embedding generation."""

    def __init__(self, weaviate_retriever: WeaviateRetriever, embedding_service: EmbeddingService):
        self.weaviate_retriever = weaviate_retriever
        self.embedding_service = embedding_service

    def retrieve(self, query: str, top_k: int = None, filters: dict = None):
        """Retrieve documents by generating embedding for the query.

        Returns:
            Tuple of (results, metadata) to match RAGOrchestrator contract.
        """
        import time
        from typing import Dict, Any

        # Generate embedding for query
        start_time = time.time()
        query_vector = self.embedding_service.generate(query)
        embedding_time_ms = (time.time() - start_time) * 1000

        # Use near_vector search instead of hybrid
        from weaviate.classes.query import MetadataQuery
        k = top_k or self.weaviate_retriever.top_k

        metadata: Dict[str, Any] = {
            "query": query[:100],
            "top_k": k,
            "embedding_time_ms": round(embedding_time_ms, 2),
            "search_time_ms": None,
            "total_time_ms": None,
            "error": None,
            "error_type": None,
            "low_relevance": False,
            "avg_score": None,
        }

        try:
            log.debug("Executing vector search: query=%s, top_k=%d", query[:50], k)

            search_start = time.time()
            active_filters = self.weaviate_retriever._build_filters(filters)
            response = self.weaviate_retriever.collection.query.near_vector(
                near_vector=query_vector,
                limit=k,
                filters=active_filters,
                return_metadata=MetadataQuery(score=True, distance=True),
            )
            search_time_ms = (time.time() - search_start) * 1000
            metadata["search_time_ms"] = round(search_time_ms, 2)

            results = []
            scores = []
            for obj in response.objects:
                score = obj.metadata.score if obj.metadata else 0.0
                scores.append(score)

                doc = {
                    "uuid": str(obj.uuid),
                    "text": obj.properties.get("text", ""),
                    "source": obj.properties.get("source", ""),
                    "chunk_index": obj.properties.get("chunk_index", 0),
                    "score": score,
                    "distance": obj.metadata.distance if obj.metadata else None,
                }
                results.append(doc)

            # Calculate metrics
            total_time_ms = (time.time() - start_time) * 1000
            metadata["total_time_ms"] = round(total_time_ms, 2)

            if scores:
                avg_score = sum(scores) / len(scores)
                metadata["avg_score"] = round(avg_score, 3)
                metadata["low_relevance"] = avg_score < 0.5

            log.info(
                "Retrieved %d documents for query: %s (avg_score=%.3f)",
                len(results), query[:50], metadata.get("avg_score", 0.0)
            )
            return results, metadata

        except Exception as e:
            log.error("Retrieval failed for query '%s': %s", query[:50], e)
            metadata["error"] = str(e)
            metadata["error_type"] = "unknown"
            metadata["total_time_ms"] = round((time.time() - start_time) * 1000, 2)
            return None, metadata


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

    # Initialize embedding service
    log.info("Initializing embedding service")
    model_manager = ModelManager(
        api_roots=config._lmstudio_api_roots,
        require_live=config.LMSTUDIO_REQUIRE_SERVER
    )
    embedding_service = EmbeddingService(config, model_manager)

    # Create Weaviate retriever
    weaviate_retriever = WeaviateRetriever(
        client=weaviate_client,
        collection_name=config.WEAVIATE_CLASS,
        tenant=config.WEAVIATE_DEFAULT_TENANT if config.WEAVIATE_MULTI_TENANCY else None,
        top_k=5,  # Default number of results
    )

    # Wrap with EmbeddingWeaviateRetriever to handle query embedding
    retriever = EmbeddingWeaviateRetriever(
        weaviate_retriever=weaviate_retriever,
        embedding_service=embedding_service,
    )

    # Create chat service
    # Use the first language model (not embedding model)
    language_model = model_manager.get_first_language_model() if not config.LMSTUDIO_CHAT_MODEL else config.LMSTUDIO_CHAT_MODEL
    chat_service = LMStudioChatService(
        base_url=f"http://{config.LMSTUDIO_HOST}:{config.LMSTUDIO_PORT}/v1",
        api_key="lm-studio",
        model=language_model,
    )

    # Create RAG orchestrator
    # Note: Disable RAG gating in CLI mode to ensure RAG always runs
    # In CLI, users explicitly query the knowledge base and expect retrieval
    rag = RAGOrchestrator(
        retriever=retriever,
        chat_service=chat_service,
        include_sources=True,
        enable_rag_gating=False,  # Always use RAG in CLI mode
    )

    log.info("RAG system initialized successfully")
    return rag


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

    # Load configuration
    try:
        config = AppConfig()
        log.info("Configuration loaded successfully")
    except Exception as e:
        print(f"Failed to load configuration: {e}")
        sys.exit(1)

    # Initialize RAG system
    try:
        rag = create_rag_system(config)
    except Exception as e:
        print(f"Failed to initialize RAG system: {e}")
        log.error("RAG initialization failed", exc_info=True)
        sys.exit(1)

    # Run in appropriate mode
    if args.question and args.query:
        print("Provide either a positional query or --question, not both.")
        sys.exit(2)

    question = args.question or (" ".join(args.query).strip() if args.query else None)
    if question:
        single_query_mode(rag, question, args.top_k)
    else:
        interactive_mode(rag)


if __name__ == "__main__":
    main()
