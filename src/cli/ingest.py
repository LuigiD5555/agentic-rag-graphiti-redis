"""Ingest documents and code into a vector database using embeddings."""

import argparse
from src.config.settings import Config
from src.providers.lmstudio.model_manager import ModelManager
from src.providers.lmstudio.embeddings import EmbeddingService
from src.ingestion.pipeline import IngestionPipeline
from src.vectorstores import get_vector_store


def main():
    """
    Main entry point for the ingestion module.

    Parses command-line arguments, initializes configuration and services,
    and runs the ingestion pipeline to process and persist documents.
    """
    ap = argparse.ArgumentParser(description="Ingest documents and code into vector DB (embeddings only).")
    ap.add_argument("paths", nargs="+", help="Directories or files to ingest.")
    args = ap.parse_args()

    cfg = Config()

    # Model manager base URL (strip /v1/embeddings if present)
    api_root = cfg.LM_EMBED_URL.rstrip("/")
    if api_root.endswith("/v1/embeddings"):
        api_root = api_root.rsplit("/v1/embeddings", 1)[0]
    mm = ModelManager(api_root)

    embedding_service = EmbeddingService(cfg, mm)
    vector_store = get_vector_store(cfg)

    pipeline = IngestionPipeline(
        embedding_service=embedding_service,
        vector_store=vector_store,
        chunk_size=cfg.CHUNK_SIZE,
        chunk_overlap=cfg.CHUNK_OVERLAP,
    )
    pipeline.ingest_paths(args.paths)


if __name__ == "__main__":
    main()
