"""CLI for querying the RAG system."""
import argparse
import asyncio
import sys

from src.api.runtime import RuntimeFactory
from src.workflows.query.engine import AppConfig
from src.workflows.query.pipeline.rag_orchestrator import RAGOrchestrator
from src.workflows.query.audit import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Swarm engine helpers
# ---------------------------------------------------------------------------

def _build_swarm_pipeline():
    from experiments.swarm_rag.core.pipeline import SwarmPipeline
    from src.backends.llm.factory import ProviderFactory
    from src.conf import settings

    config = AppConfig()
    provider_factory = ProviderFactory(config)
    chat = provider_factory.chat()
    embedding_service = provider_factory.embeddings()

    weaviate_retriever = None
    _weaviate_client = None
    try:
        import weaviate as wv
        from src.workflows.query.retrieval import WeaviateRetriever
        _weaviate_client = wv.connect_to_local(
            host=getattr(settings, "WEAVIATE_HOST", "localhost"),
            port=int(getattr(settings, "WEAVIATE_PORT", 8080)),
        )
        tenant = getattr(settings, "WEAVIATE_DEFAULT_TENANT", None) if getattr(settings, "WEAVIATE_MULTI_TENANCY", False) else None
        weaviate_retriever = WeaviateRetriever(
            client=_weaviate_client,
            collection_name=getattr(settings, "WEAVIATE_CLASS", "Document"),
            embedding_service=embedding_service,
            tenant=tenant,
            top_k=10,
        )
    except Exception as exc:
        log.warning("Weaviate unavailable (%s) — swarm will run without retrieval", exc)

    pipeline = SwarmPipeline.build(chat_interface=chat, weaviate_retriever=weaviate_retriever)
    pipeline._weaviate_client = _weaviate_client  # keep ref for cleanup
    return pipeline


def _close_swarm_pipeline(pipeline) -> None:
    client = getattr(pipeline, "_weaviate_client", None)
    if client is not None:
        try:
            client.close()
        except Exception:
            pass


def _swarm_single_query(question: str, verbose: bool = False) -> None:
    from experiments.swarm_rag.core.blackboard import Blackboard

    print(f"\nQuestion: {question}\n")
    print("Running through Swarm pipeline...\n")

    pipeline = _build_swarm_pipeline()
    try:
        async def _run():
            async with Blackboard.session(question) as (state, board):
                state = await pipeline.run(question, session_id=state.session_id)
                board.persist_state(state, written_by="cli")
            return state

        state = asyncio.run(_run())
    finally:
        _close_swarm_pipeline(pipeline)

    print("=" * 70)
    print(f"Answer:\n\n{state.final_response or '(no response)'}")
    print("=" * 70)

    if verbose:
        print(f"\nIntent: {state.perception.intent}  |  Domain: {state.perception.domain}"
              f"  |  Complexity: {state.perception.complexity}")
        print(f"Confidence: {state.reasoning.confidence_score:.2f}"
              f"  |  Escalated: {state.reasoning.escalate_to_llm}")
        print(f"Branches: {state.active_branches}")
        print("\nLatency (ms):")
        for stage_name, latency in state.latency_ms.items():
            print(f"  {stage_name:<20} {latency}")
    print()


def _swarm_interactive() -> None:
    from experiments.swarm_rag.core.blackboard import Blackboard

    print("\n===================================================================")
    print("RAG Interactive Query System  [engine: swarm]")
    print("Type your questions below. Type 'exit' or 'quit' to end")
    print("===================================================================\n")

    pipeline = _build_swarm_pipeline()
    try:
        while True:
            try:
                question = input("\nYour question: ").strip()
                question = question.encode("utf-8", errors="surrogatepass").decode("utf-8", errors="ignore")

                if not question:
                    continue
                if question.lower() in ["exit", "quit", "q"]:
                    print("\nGoodbye!")
                    break

                async def _run():
                    async with Blackboard.session(question) as (state, board):
                        state = await pipeline.run(question, session_id=state.session_id)
                        board.persist_state(state, written_by="cli_interactive")
                    return state

                state = asyncio.run(_run())

                print("=" * 70)
                print(f"Answer:\n\n{state.final_response or '(no response)'}")
                print("=" * 70)
                print(f"\nConfidence: {state.reasoning.confidence_score:.2f}"
                      f"  |  Intent: {state.perception.intent}"
                      f"  |  Escalated: {state.reasoning.escalate_to_llm}")

            except KeyboardInterrupt:
                print("\n\nInterrupted. Goodbye!")
                break
            except Exception as exc:
                log.error("Swarm query failed: %s", exc)
                print(f"\nError: {exc}\n")
    finally:
        _close_swarm_pipeline(pipeline)


# ---------------------------------------------------------------------------
# Standard RAG engine helpers
# ---------------------------------------------------------------------------

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
            result = rag.query(question=question)

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
            graph_flag = " | graph=yes" if metadata.get("used_graph_context") else ""
            web_flag = " | web=yes" if metadata.get("used_web_search") else ""
            print(f"\nRetrieved: {metadata.get('retrieved_count', 0)} chunks{graph_flag}{web_flag}")

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
        result = rag.query(question=question, top_k=top_k)

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
        graph_flag = " | graph=yes" if metadata.get("used_graph_context") else ""
        web_flag = " | web=yes" if metadata.get("used_web_search") else ""
        print(f"\nRetrieved: {metadata.get('retrieved_count', 0)} chunks{graph_flag}{web_flag}\n")

    except Exception as e:
        log.error("Query failed: %s", e)
        print(f"\nError: {e}\n")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Main entry point for query CLI."""
    parser = argparse.ArgumentParser(
        description="Query the RAG system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Interactive mode (standard RAG)
  python -m src.query.cli

  # Single query (standard RAG)
  python -m src.query.cli "What is the main topic of the documents?"

  # Single query through Swarm pipeline
  python -m src.query.cli --engine swarm "explain the contract penalties"

  # Swarm with verbose layer detail
  python -m src.query.cli --engine swarm -v "explain the contract penalties"

  # Interactive mode (Swarm)
  python -m src.query.cli --engine swarm

  # Retrieve more documents (standard RAG only)
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
        help="Number of documents to retrieve, standard engine only (default: 5)"
    )

    parser.add_argument(
        "--engine", "-e",
        choices=["rag", "swarm"],
        default="rag",
        help="Query engine to use: 'rag' (default) or 'swarm' (experimental)"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show per-layer detail (swarm engine only)"
    )

    args = parser.parse_args()

    if args.question and args.query:
        print("Provide either a positional query or --question, not both.")
        sys.exit(2)

    question = args.question or (" ".join(args.query).strip() if args.query else None)

    # --- Swarm engine path (no RuntimeFactory needed) ---
    if args.engine == "swarm":
        if question:
            _swarm_single_query(question, verbose=args.verbose)
        else:
            _swarm_interactive()
        return

    # --- Standard RAG engine path ---
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
