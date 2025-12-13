from __future__ import annotations

import os
from collections import deque
from typing import Dict, Any, Iterator, List, Optional

import pytest

from src.ingestion.pipeline import IngestionPipeline, SplitterStrategy
from src.rag.cli.options import PipelineOptions
from src.interfaces.vector_interface import VectorInterface, SupportsExists


class DummyEmbedding:
    """Test double that records sanitized text passed for embedding."""

    def __init__(self) -> None:
        self.calls: deque[str] = deque()

    def generate(self, text: str) -> List[float]:
        self.calls.append(text)
        return [0.1, 0.2, 0.3]


class DummyVectorStore(VectorInterface, SupportsExists):
    """Minimal vector store that tracks upserts for assertions."""

    def __init__(self) -> None:
        self.upserts: deque[Dict[str, Any]] = deque()
        self._existing: set[str] = set()
        self.failures: deque[Dict[str, Any]] = deque()
        self.archived: deque[str] = deque()

    def upsert(
        self,
        key: Optional[str],
        vector: List[float],
        metadata: Dict[str, Any],
        tenant_id: Optional[str] = None,
    ) -> None:
        self.upserts.append(
            {
                "key": key,
                "vector": list(vector),
                "metadata": dict(metadata),
                "tenant_id": tenant_id,
            }
        )
        if key:
            self._existing.add(key)

    def search(
        self,
        vector: List[float],
        top_k: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        tenant_id: Optional[str] = None,
    ):
        return []

    def iter_payloads(self, batch_size: int = 256, tenant_id: Optional[str] = None) -> Iterator[Dict[str, Any]]:
        return iter(())

    def exists(self, point_id: str, tenant_id: Optional[str] = None) -> bool:
        return point_id in self._existing

    def upsert_failure(self, record: Dict[str, Any]) -> None:
        self.failures.append(record)

    def archive_file(self, file_id: str, tenant_id: Optional[str] = None) -> None:
        self.archived.append(file_id)


class FailingLoader:
    def __init__(self, path: str):
        self.path = path

    def load(self):
        from src.ingestion.loaders.errors import LoaderError

        raise LoaderError("boom")


def test_ingestion_pipeline_sanitizes_and_upserts(tmp_path):
    target = tmp_path / "doc.txt"
    target.write_text("Hola\u2028RAG!\nAnother line.", encoding="utf-8")

    embedding = DummyEmbedding()
    vector_store = DummyVectorStore()
    pipeline = IngestionPipeline(
        embedding_service=embedding,
        vector_store=vector_store,
        options=PipelineOptions(
            chunk_size=20,
            chunk_overlap=0,
            owner_id="user-1",
            visibility="shared",
            allowed_user_ids=["user-2"],
            tenant_id="tenant-A",
            splitter_strategy=SplitterStrategy.RECURSIVE,
        ),
    )

    pipeline.ingest_paths([str(tmp_path)])

    assert vector_store.upserts, "The pipeline should upsert at least one processed chunk."

    for upsert in vector_store.upserts:
        metadata = upsert["metadata"]
        assert metadata["owner_id"] == "user-1"
        assert metadata["visibility"] == "shared"
        assert metadata["allowed_user_ids"] == ["user-2"]
        assert "hash" in metadata
        assert metadata["content"], "Stored metadata must include sanitized content."
        assert "\u2028" not in metadata["content"], "Sanitization should strip control characters."
        assert upsert["tenant_id"] == "tenant-A"

    # Ensure embedding was called for each stored chunk
    assert len(embedding.calls) == len(vector_store.upserts)
    for text in embedding.calls:
        assert "\u2028" not in text


@pytest.mark.skipif(not hasattr(os, "symlink"), reason="Symlinks not supported on this platform.")
def test_ingestion_pipeline_skips_broken_symlink(tmp_path):
    origin = tmp_path / "missing.txt"
    broken_link = tmp_path / "broken.txt"
    try:
        broken_link.symlink_to(origin)
    except OSError as exc:  # pragma: no cover - depends on filesystem permissions
        pytest.skip(f"Unable to create symlink: {exc}")

    embedding = DummyEmbedding()
    vector_store = DummyVectorStore()
    pipeline = IngestionPipeline(
        embedding_service=embedding,
        vector_store=vector_store,
        options=PipelineOptions(
            chunk_size=20,
            chunk_overlap=0,
        ),
    )

    pipeline.ingest_paths([str(broken_link)])

    assert not vector_store.upserts
    assert not embedding.calls


def test_ingestion_pipeline_accepts_file_path(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("# Title\n\nContent.", encoding="utf-8")

    embedding = DummyEmbedding()
    vector_store = DummyVectorStore()
    pipeline = IngestionPipeline(
        embedding_service=embedding,
        vector_store=vector_store,
        options=PipelineOptions(
            chunk_size=20,
            chunk_overlap=0,
            splitter_strategy=SplitterStrategy.MARKDOWN_HEADERS,
        ),
    )

    pipeline.ingest_paths([str(doc)])

    assert vector_store.upserts
    assert embedding.calls


def test_loader_failure_is_recorded(tmp_path):
    doc = tmp_path / "doc.txt"
    doc.write_text("hi", encoding="utf-8")
    embedding = DummyEmbedding()
    vector_store = DummyVectorStore()
    pipeline = IngestionPipeline(
        embedding_service=embedding,
        vector_store=vector_store,
        options=PipelineOptions(chunk_size=20, chunk_overlap=0),
    )

    # call processor directly to force loader error path
    from src.ingestion.pipeline.text_processor import process_text_document

    process_text_document(pipeline, FailingLoader(str(doc)))

    assert vector_store.failures, "Loader errors should be recorded via upsert_failure."
    assert vector_store.failures[0]["failure_reason"] == "loader_skip"


def test_embedding_token_limit_splits_chunks(tmp_path):
    doc = tmp_path / "long.txt"
    tokens = [f"tok{i}" for i in range(10)]
    doc.write_text(" ".join(tokens), encoding="utf-8")

    embedding = DummyEmbedding()
    vector_store = DummyVectorStore()
    pipeline = IngestionPipeline(
        embedding_service=embedding,
        vector_store=vector_store,
        options=PipelineOptions(
            chunk_size=100,
            chunk_overlap=0,
            embedding_token_limit=3,
            splitter_strategy=SplitterStrategy.RECURSIVE,
        ),
    )

    pipeline.ingest_paths([str(doc)])

    assert len(vector_store.upserts) == 5
    assert len(embedding.calls) == 5
    for upsert in vector_store.upserts:
        metadata = upsert["metadata"]
        assert len(metadata["content"].split()) <= 2
        assert metadata["chunk_total"] == 5


def test_truncate_respects_token_limit(tmp_path):
    doc = tmp_path / "long2.txt"
    tokens = [f"tok{i}" for i in range(12)]
    doc.write_text(" ".join(tokens), encoding="utf-8")

    embedding = DummyEmbedding()
    vector_store = DummyVectorStore()
    pipeline = IngestionPipeline(
        embedding_service=embedding,
        vector_store=vector_store,
        options=PipelineOptions(
            chunk_size=100,
            chunk_overlap=0,
            embedding_token_limit=6,  # will be trimmed with safety margin
            splitter_strategy=SplitterStrategy.RECURSIVE,
            tokenizer_model_name="gpt-4o-mini",
        ),
    )

    pipeline.ingest_paths([str(doc)])

    assert vector_store.upserts
    for upsert in vector_store.upserts:
        content_tokens = upsert["metadata"]["content"].split()
        assert len(content_tokens) <= 4  # effective limit after margin
