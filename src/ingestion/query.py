"""Simple CLI to ingest explicit paths."""
import argparse

from src.ingestion.options import PipelineOptions
from src.ingestion.pipeline import IngestionPipeline
from src.providers.factory import ProviderFactory
import src.settings as settings
from src.rag.embeddings_factory import get_embedding_service
from src.storage.vector import get_vector_store


def main():
    """Main entry point for the ingestion CLI."""
    ap = argparse.ArgumentParser(
        description="Ingest documents and code into vector DB (embeddings only)."
    )
    ap.add_argument("--paths", nargs="+", required=True)
    args = ap.parse_args()

    provider = ProviderFactory(settings)
    embed = get_embedding_service(settings, provider)
    vector = get_vector_store(settings)

    pipeline_options = PipelineOptions(
        chunk_size=settings.CHUNK_SIZE,
        chunk_overlap=settings.CHUNK_OVERLAP,
        embedding_token_limit=settings.EMBEDDING_MAX_TOKENS,
        tenant_id=(settings.WEAVIATE_DEFAULT_TENANT or None),
    )
    pipeline = IngestionPipeline.from_options(
        embedding_service=embed,
        vector_store=vector,
        options=pipeline_options,
    )
    pipeline.ingest_paths(args.paths)


__all__ = ["main"]


if __name__ == "__main__":
    main()
