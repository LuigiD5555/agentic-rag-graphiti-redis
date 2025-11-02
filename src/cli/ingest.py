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

    mm = ModelManager(
        cfg.LMSTUDIO_API_ROOTS,
        require_live=cfg.LMSTUDIO_REQUIRE_SERVER,
    )

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
