"""
Module for ingesting documents and code into vector database.
"""
import argparse
from src.config.settings import Config
from src.providers.factory import ProviderFactory
from src.storage.vector import get_vector_store
from src.ingestion.pipeline import IngestionPipeline
from src.cli.options import PipelineOptions


def main():
    """Main entry point for the ingestion CLI."""
    ap = argparse.ArgumentParser(
        description="Ingest documents and code into vector DB (embeddings only)."
    )
    ap.add_argument("--paths", nargs="+", required=True)
    args = ap.parse_args()

    cfg = Config()
    provider = ProviderFactory(cfg)
    embed = provider.embeddings()
    vector = get_vector_store(cfg)

    pipeline_options = PipelineOptions(
        chunk_size=cfg.CHUNK_SIZE,
        chunk_overlap=cfg.CHUNK_OVERLAP,
        embedding_token_limit=cfg.EMBEDDING_MAX_TOKENS,
        tenant_id=(cfg.WEAVIATE_DEFAULT_TENANT or None),
    )
    pipeline = IngestionPipeline.from_options(
        embedding_service=embed,
        vector_store=vector,
        options=pipeline_options,
    )
    pipeline.ingest_paths(args.paths)


if __name__ == "__main__":
    main()
