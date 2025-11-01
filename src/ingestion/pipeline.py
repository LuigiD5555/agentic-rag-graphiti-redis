"""
Document ingestion pipeline: loads files, splits content with modern LangChain splitters,
generates embeddings, and persists them via a vector interface.
"""

from __future__ import annotations

import os
import unicodedata
import hashlib
from enum import Enum
from typing import List, Optional, Iterable

# Modern splitters live in the separate package `langchain_text_splitters`
from langchain_text_splitters import (
    TokenTextSplitter,
    RecursiveCharacterTextSplitter,
    MarkdownHeaderTextSplitter,
)
try:
    from langchain_core.documents import Document  # modern LangChain import location
except ImportError:  # pragma: no cover - backwards compat for older LangChain versions
    from langchain.schema import Document  # type: ignore

# Optional: semantic splitting (experimental)
try:
    from langchain_experimental.text_splitter import SemanticChunker  # type: ignore
except ImportError:
    SemanticChunker = None  # type: ignore

from src.interfaces.embedding_interface import EmbeddingInterface
from src.interfaces.vector_interface import VectorInterface, SupportsExists
from src.ingestion.loaders.pdf_loader import PDFLoader
from src.ingestion.loaders.docx_loader import DocxLoader
from src.ingestion.loaders.text_loader import PlainTextLoader
from src.ingestion.loaders.md_loader import MarkdownLoader
from src.ingestion.loaders.py_loader import PythonCodeStructure
from src.ingestion.loaders.js_loader import JavaScriptCodeStructure
from src import logger


class SplitterStrategy(str, Enum):
    """Available text splitting strategies."""
    TOKEN = "token"                  # token-aware via tiktoken (recommended default)
    RECURSIVE = "recursive"          # character-based, robust generic splitter
    MARKDOWN_HEADERS = "md_headers"  # respects Markdown header hierarchy
    SEMANTIC = "semantic"            # embeddings-based (experimental)


class IngestionPipeline:
    """Pipeline for ingesting documents and generating embeddings using modern splitters."""

    def __init__(
        self,
        embedding_service: EmbeddingInterface,
        vector_store: VectorInterface,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        owner_id: Optional[str] = None,
        visibility: str = "private",
        allowed_user_ids: Optional[List[str]] = None,
        tenant_id: Optional[str] = None,
        splitter_strategy: SplitterStrategy = SplitterStrategy.TOKEN,
        tokenizer_model_name: str = "gpt-4o-mini",
        markdown_levels: Optional[dict[str, int]] = None,  # e.g. {"#": 1, "##": 2, "###": 3}
        semantic_embeddings: Optional[object] = None,       # LangChain Embeddings if using SEMANTIC
    ):
        """
        Initialize the ingestion pipeline.

        Args:
            embedding_service: Service to generate embeddings.
            vector_store: Storage interface for vector data.
            chunk_size: Maximum size of each chunk (tokens for TOKEN, chars for RECURSIVE; ignored for pure MD headers).
            chunk_overlap: Overlap between consecutive chunks.
            owner_id: Logical owner/user id for access control metadata.
            visibility: Visibility level (e.g., "private" | "shared" | "public").
            allowed_user_ids: Optional list of user ids who may access the content.
            tenant_id: Multi-tenant segregation id; forwarded to vector store when supported.
            splitter_strategy: Strategy for splitting: token/recursive/md_headers/semantic.
            tokenizer_model_name: Tokenizer name used by TOKEN strategy.
            markdown_levels: Header map for Markdown header splitter (only for md_headers).
            semantic_embeddings: LangChain Embeddings instance (only for semantic).
        """
        self.embedding_service = embedding_service
        self.vector_store = vector_store

        self.owner_id = owner_id
        self.visibility = visibility
        self.allowed_user_ids = allowed_user_ids or []
        self.tenant_id = tenant_id

        self.splitter_strategy = splitter_strategy
        self.tokenizer_model_name = tokenizer_model_name
        self.markdown_levels = markdown_levels or {"#": 1, "##": 2, "###": 3}
        self.semantic_embeddings = semantic_embeddings

        self.text_splitter = self._build_text_splitter(
            strategy=splitter_strategy,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            tokenizer_model_name=tokenizer_model_name,
            markdown_levels=self.markdown_levels,
            semantic_embeddings=semantic_embeddings,
        )

    def ingest_paths(self, paths: List[str]) -> None:
        """
        Ingest documents from a list of directory paths.

        Args:
            paths: List of directory paths to process.
        """
        for path in paths:
            if not os.path.exists(path):
                logger.error("Path does not exist: %s", path)
                continue

            for root, _, files in os.walk(path):
                for filename in files:
                    full_path = os.path.join(root, filename)

                    if filename.endswith(".pdf"):
                        self._process_text_document(PDFLoader(full_path))
                    elif filename.endswith(".docx"):
                        self._process_text_document(DocxLoader(full_path))
                    elif filename.endswith(".txt"):
                        self._process_text_document(PlainTextLoader(full_path))
                    elif filename.endswith(".md"):
                        self._process_text_document(MarkdownLoader(full_path))
                    elif filename.endswith(".py"):
                        self._process_code_document(PythonCodeStructure(full_path))
                    elif filename.endswith(".js"):
                        self._process_code_document(JavaScriptCodeStructure(full_path))

    def _process_text_document(self, loader) -> None:
        """
        Load and process a text-based document.

        Args:
            loader: A document loader instance with `load()` -> List[Document].
        """
        documents: List[Document] = loader.load()

        for chunk in self._split_documents(documents):
            sanitized_text = self._sanitize_text(chunk.page_content)
            content_hash = self._generate_hash(sanitized_text)

            if self._vector_store_contains(content_hash):
                continue

            embedding = self.embedding_service.generate(sanitized_text)

            # Prepare metadata carefully, preserving loader metadata and adding access controls.
            metadata = dict(getattr(chunk, "metadata", {}) or {})
            metadata.update({
                "content": sanitized_text,
                "source": metadata.get("source", "document"),
                "visibility": self.visibility,
                "owner_id": self.owner_id,
                "allowed_user_ids": self.allowed_user_ids,
                "hash": content_hash,
            })

            # Some vector stores accept tenant_id as a separate kwarg; keep compatibility.
            try:
                self.vector_store.upsert(
                    content_hash,
                    embedding,
                    metadata,
                    tenant_id=self.tenant_id,  # type: ignore[arg-type]
                )
            except TypeError:
                # Fallback for stores that do not support tenant_id as kwarg.
                self.vector_store.upsert(
                    content_hash,
                    embedding,
                    metadata,
                )

    def _process_code_document(self, code_loader) -> None:
        """
        Load and process a code-based document.

        Args:
            code_loader: A code structure loader instance with `load_structure_summary() -> str`.
        """
        summary_text = self._sanitize_text(code_loader.load_structure_summary())
        summary_hash = self._generate_hash(summary_text)

        if self._vector_store_contains(summary_hash):
            return

        embedding = self.embedding_service.generate(summary_text)

        metadata = {
            "type": "code_context",
            "structure_summary": summary_text,
            "visibility": self.visibility,
            "owner_id": self.owner_id,
            "allowed_user_ids": self.allowed_user_ids,
            "hash": summary_hash,
        }

        try:
            self.vector_store.upsert(
                summary_hash,
                embedding,
                metadata,
                tenant_id=self.tenant_id,  # type: ignore[arg-type]
            )
        except TypeError:
            self.vector_store.upsert(summary_hash, embedding, metadata)

    # ---------- helpers ----------

    def _build_text_splitter(
        self,
        strategy: SplitterStrategy,
        chunk_size: int,
        chunk_overlap: int,
        tokenizer_model_name: str,
        markdown_levels: dict[str, int],
        semantic_embeddings: Optional[object],
    ):
        """
        Factory that returns a modern text splitter instance.

        Returns:
            A configured splitter instance from `langchain_text_splitters`
            (or `langchain_experimental` for semantic).
        """
        if strategy == SplitterStrategy.TOKEN:
            # Token-aware splitter (sizes are in tokens).
            return TokenTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                model_name=tokenizer_model_name,
            )

        if strategy == SplitterStrategy.RECURSIVE:
            return RecursiveCharacterTextSplitter(
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )

        if strategy == SplitterStrategy.MARKDOWN_HEADERS:
            # This splitter returns chunks by Markdown header hierarchy.
            return MarkdownHeaderTextSplitter(headers_to_split_on=markdown_levels)

        if strategy == SplitterStrategy.SEMANTIC:
            if SemanticChunker is None:
                raise ImportError(
                    "SemanticChunker is not available. Install `langchain-experimental`."
                )
            if semantic_embeddings is None:
                raise ValueError(
                    "semantic_embeddings is required for SplitterStrategy.SEMANTIC."
                )
            # `buffer_size` acts like overlap; `chunk_size` hints target size.
            return SemanticChunker(
                semantic_embeddings,
                breakpoint_threshold_type="percentile",
                buffer_size=chunk_overlap,
                chunk_size=chunk_size,
            )

        raise ValueError(f"Unknown splitting strategy: {strategy}")

    def _split_documents(self, documents: List[Document]) -> Iterable[Document]:
        """
        Split a list of Documents according to the configured splitter.

        Notes:
            - TokenTextSplitter and RecursiveCharacterTextSplitter expose `.split_documents`.
            - MarkdownHeaderTextSplitter exposes `.split_text` and expects raw text; we
              call it per input document and propagate metadata.
            - SemanticChunker exposes `.split_documents`.
        """
        # Markdown header splitter has a different API (split_text)
        if isinstance(self.text_splitter, MarkdownHeaderTextSplitter):
            for doc in documents:
                md_chunks = self.text_splitter.split_text(doc.page_content)
                for ch in md_chunks:
                    # Propagate original metadata into each chunk.
                    merged_meta = dict(doc.metadata or {})
                    merged_meta.update(ch.metadata or {})
                    yield Document(page_content=ch.page_content, metadata=merged_meta)
            return

        # All other splitters should implement split_documents(...)
        if hasattr(self.text_splitter, "split_documents"):
            yield from self.text_splitter.split_documents(documents)  # type: ignore[misc]
            return

        # Safety net: if no known method exists, fall back to identity.
        for doc in documents:
            yield doc

    @staticmethod
    def _sanitize_text(text: str) -> str:
        """
        Normalize and clean text by removing non-printable characters.

        Args:
            text: Raw input text.

        Returns:
            Sanitized text.
        """
        normalized = unicodedata.normalize("NFC", str(text))
        encoded = normalized.encode("utf-8", errors="replace").decode("utf-8")
        return "".join(
            char if (char.isprintable() or char in "\n\t") else " " for char in encoded
        )

    def _generate_hash(self, text: str) -> str:
        """
        Generate a SHA-256 hash of the sanitized text.

        Args:
            text: Input text.

        Returns:
            Hexadecimal hash string.
        """
        sanitized = self._sanitize_text(text)
        return hashlib.sha256(sanitized.encode("utf-8")).hexdigest()

    def _vector_store_contains(self, hash_id: str) -> bool:
        """
        Check if the vector store already contains the given hash.

        Args:
            hash_id: Hash identifier.

        Returns:
            True if exists, False otherwise.
        """
        if isinstance(self.vector_store, SupportsExists):
            try:
                return self.vector_store.exists(hash_id)
            except AttributeError:
                return False
        return False
