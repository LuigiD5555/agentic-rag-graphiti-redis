#!/usr/bin/env python3
"""Verify that queries return partial results while ingestion is running."""
import argparse
import threading
import time
from typing import Optional

import weaviate

from src.workflows.ingestion.helpers import build_ingestion_options_from_args
from src.workflows.ingestion.orchestrator import IngestionOrchestrator
import src.settings as settings
from src.workflows.query.engine import AppConfig
from src.workflows.query.retrieval import WeaviateRetriever


def _connect_weaviate(app_cfg: AppConfig):
    host = app_cfg.WEAVIATE_URL.replace("http://", "").replace("https://", "").split(":")[0]
    port = int(app_cfg.WEAVIATE_URL.split(":")[-1]) if ":" in app_cfg.WEAVIATE_URL else 8080
    return weaviate.connect_to_local(
        host=host,
        port=port,
        grpc_port=app_cfg.WEAVIATE_GRPC_PORT,
    )


def _build_retriever(app_cfg: AppConfig, client) -> WeaviateRetriever:
    tenant = app_cfg.WEAVIATE_DEFAULT_TENANT if app_cfg.WEAVIATE_MULTI_TENANCY else None
    return WeaviateRetriever(
        client=client,
        collection_name=app_cfg.WEAVIATE_CLASS,
        tenant=tenant,
        top_k=5,
    )


def _run_ingestion(orchestrator: IngestionOrchestrator, options) -> None:
    orchestrator.run(options)


def _poll_retriever(
    retriever: WeaviateRetriever,
    query: str,
    top_k: int,
    label: Optional[str] = None,
) -> None:
    results = retriever.retrieve(query=query, top_k=top_k)
    prefix = f"{label} " if label else ""
    print(f"{prefix}retrieved={len(results)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify streaming ingestion with concurrent queries.")
    parser.add_argument("paths", nargs="*", help="Root directories or files to ingest.")
    parser.add_argument("--query", required=True, help="Query to run while ingestion is active.")
    parser.add_argument("--top-k", type=int, default=5, help="Top-k results to fetch per poll.")
    parser.add_argument("--interval", type=float, default=5.0, help="Seconds between polls.")
    parser.add_argument("--max-polls", type=int, default=0, help="Stop after N polls (0 = until ingest ends).")
    parser.add_argument(
        "--streaming",
        dest="streaming",
        action="store_true",
        default=None,
        help="Enable streaming ingestion (default: uses INGEST_STREAMING from .env).",
    )
    parser.add_argument(
        "--no-streaming",
        dest="streaming",
        action="store_false",
        help="Disable streaming ingestion.",
    )

    parser.add_argument("--exts", nargs="+", default=None, help="Extensions to include.")
    parser.add_argument("--exclude-dirs", nargs="+", default=None, help="Directory NAMES to exclude.")
    parser.add_argument("--exclude-patterns", nargs="+", default=None, help="Glob patterns to exclude.")
    parser.add_argument("--follow-symlinks", action="store_true", help="Follow symlinks while scanning.")
    parser.add_argument("--per-file", action="store_true", help="Ingest one file at a time.")
    parser.add_argument("--max-files", type=int, default=0, help="Limit the number of files to ingest.")
    parser.add_argument("--scan-progress", type=int, default=0, help="Log scan progress every N directories.")
    parser.add_argument("--log-level", default=None, help="Python log level for ingestion.")
    args = parser.parse_args()

    app_cfg = AppConfig()

    options = build_ingestion_options_from_args(args, settings)

    orchestrator = IngestionOrchestrator()
    ingest_thread = threading.Thread(target=_run_ingestion, args=(orchestrator, options), daemon=True)
    ingest_thread.start()

    client = _connect_weaviate(app_cfg)
    retriever = _build_retriever(app_cfg, client)

    try:
        polls = 0
        while ingest_thread.is_alive():
            polls += 1
            try:
                _poll_retriever(retriever, args.query, args.top_k, label="poll")
            except Exception as exc:
                print(f"poll error: {exc}")
            if args.max_polls and polls >= args.max_polls:
                break
            time.sleep(args.interval)

        ingest_thread.join()
        _poll_retriever(retriever, args.query, args.top_k, label="final")
    finally:
        client.close()


if __name__ == "__main__":
    main()
