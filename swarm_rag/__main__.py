"""
SWARM RAG — demo CLI.

Usage:
    python -m swarm_rag "¿Cuál es la penalización del contrato vigente?"
    python -m swarm_rag --verbose "calcula el 15% de reducción"

Wires up the full pipeline using the project's existing LM Studio / Ollama
provider and Weaviate client.

Environment requirements (same as the main app):
    PROVIDER=lmstudio  (or ollama)
    LMSTUDIO_HOST / OLLAMA_HOST
    WEAVIATE_HOST (optional, for knowledge retrieval)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s %(name)s: %(message)s",
)


def _build_pipeline():
    from src.backends.llm.factory import ProviderFactory
    from src.workflows.query.engine import AppConfig
    from swarm_rag.core.pipeline import SwarmPipeline

    config = AppConfig()
    chat = ProviderFactory(config).chat()

    # Try to connect Weaviate
    weaviate_retriever = None
    try:
        import weaviate as wv
        from src.workflows.query.retrieval import WeaviateRetriever
        from src.conf import settings
        client = wv.connect_to_local(
            host=os.getenv("WEAVIATE_HOST", "localhost"),
            port=int(os.getenv("WEAVIATE_PORT", "8080")),
        )
        weaviate_retriever = WeaviateRetriever(
            client=client,
            collection_name=getattr(settings, "WEAVIATE_CLASS", "Document"),
            top_k=10,
        )
        logging.getLogger(__name__).info("Weaviate connected")
    except Exception as exc:
        logging.getLogger(__name__).warning("Weaviate unavailable (%s) — no retrieval", exc)

    # Try to connect Neo4j
    neo4j_repo = None
    try:
        from src.backends.storage.graph.neo4j_repository import Neo4jRepository
        from src.conf import settings as s
        if getattr(s, "NEO4J_URI", ""):
            neo4j_repo = Neo4jRepository(s)
            logging.getLogger(__name__).info("Neo4j connected")
    except Exception as exc:
        logging.getLogger(__name__).warning("Neo4j unavailable (%s) — no graph retrieval", exc)

    return SwarmPipeline.build(
        chat_interface=chat,
        weaviate_retriever=weaviate_retriever,
        neo4j_repository=neo4j_repo,
    )


def _print_result(state, verbose: bool) -> None:
    print("\n" + "=" * 70)
    print("SWARM RAG RESPONSE")
    print("=" * 70)
    print(state.final_response or "(no response)")
    print()

    if verbose:
        print("─" * 70)
        print(f"Intent:      {state.perception.intent}")
        print(f"Domain:      {state.perception.domain}")
        print(f"Complexity:  {state.perception.complexity}")
        print(f"Language:    {state.perception.language}")
        print(f"Math:        {state.perception.needs_math}")
        print(f"Code:        {state.perception.needs_code}")
        print()
        print(f"Confidence:  {state.reasoning.confidence_score:.2f}")
        print(f"Escalated:   {state.reasoning.escalate_to_llm}")
        print(f"Branches:    {state.active_branches}")
        print()
        print("Latency (ms):")
        for k, v in state.latency_ms.items():
            print(f"  {k:<20} {v}")
        print("─" * 70)

        if state.reasoning.structured_answer:
            print("\nSTRUCTURED CONTEXT (sent to SLM):")
            print(state.reasoning.structured_answer[:800])
            print()


def main() -> None:
    parser = argparse.ArgumentParser(description="SWARM RAG demo")
    parser.add_argument("query", nargs="?", help="Query to process")
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    if not args.query:
        parser.print_help()
        sys.exit(1)

    print(f"Building pipeline...", file=sys.stderr)
    pipeline = _build_pipeline()

    print(f"Processing: {args.query[:80]}", file=sys.stderr)
    state = asyncio.run(pipeline.run(args.query))

    if args.json:
        out = {
            "final_response": state.final_response,
            "confidence_score": state.reasoning.confidence_score,
            "escalated": state.reasoning.escalate_to_llm,
            "intent": state.perception.intent,
            "domain": state.perception.domain,
            "latency_ms": state.latency_ms,
        }
        print(json.dumps(out, ensure_ascii=False, indent=2))
    else:
        _print_result(state, args.verbose)


if __name__ == "__main__":
    main()
