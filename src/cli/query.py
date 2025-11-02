"""
Module for ingesting documents and code into vector database.
"""
import argparse
from src.config.settings import Config
from src.providers.lmstudio.model_manager import ModelManager
from src.providers.lmstudio.embeddings import EmbeddingService
from src.storage.vector.weaviate_repository import WeaviateRepository
from src.ingestion.pipeline import IngestionPipeline


def main():
    """Main entry point for the ingestion CLI."""
    ap = argparse.ArgumentParser(
        description="Ingest documents and code into vector DB (embeddings only)."
    )
    ap.add_argument("--paths", nargs="+", required=True)
    args = ap.parse_args()

    cfg = Config()
    mm = ModelManager(
        cfg.LMSTUDIO_API_ROOTS,
        require_live=cfg.LMSTUDIO_REQUIRE_SERVER,
    )

    embed = EmbeddingService(cfg, mm)
    vector = WeaviateRepository(cfg)

    pipeline = IngestionPipeline(
        embedding_service=embed,
        vector_store=vector,
        chunk_size=cfg.CHUNK_SIZE,
        chunk_overlap=cfg.CHUNK_OVERLAP
    )
    pipeline.ingest_paths(args.paths)


if __name__ == "__main__":
    main()
