"""
Document ingestion pipeline: loads files, splits content with modern LangChain splitters,
generates embeddings, and persists them via a vector interface.
"""

from __future__ import annotations

import os
import unicodedata
import hashlib
from enum import Enum
from datetime import datetime, timezone, timedelta
import re
from typing import Iterable, List, Optional, Sequence

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
        markdown_levels: Optional[object] = None,  # e.g. [("#", "Header 1"), ("##", "Header 2")]
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
            markdown_levels: Header map (dict or list of (separator, label) pairs) for Markdown header splitter.
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
        self.markdown_levels = self._normalize_markdown_headers(markdown_levels)
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
            if self._should_skip_path(path):
                continue

            if os.path.isfile(path):
                self._process_candidate_file(path)
                continue

            for root, _, files in os.walk(path):
                for filename in files:
                    full_path = os.path.join(root, filename)
                    self._process_candidate_file(full_path)

    def _process_candidate_file(self, full_path: str) -> None:
        """
        Dispatch a file to the appropriate loader if supported.

        Args:
            full_path: Absolute path to the file.
        """
        if self._should_skip_path(full_path):
            return

        if full_path.endswith(".pdf"):
            self._process_text_document(PDFLoader(full_path))
        elif full_path.endswith(".docx"):
            self._process_text_document(DocxLoader(full_path))
        elif full_path.endswith(".txt"):
            self._process_text_document(PlainTextLoader(full_path))
        elif full_path.endswith(".md"):
            self._process_text_document(MarkdownLoader(full_path))
        elif full_path.endswith(".py"):
            self._process_code_document(PythonCodeStructure(full_path))
        elif full_path.endswith(".js"):
            self._process_code_document(JavaScriptCodeStructure(full_path))

    def _should_skip_path(self, path: str) -> bool:
        """
        Determine whether a path should be skipped due to being missing or a broken symlink.

        Args:
            path: File or directory path to validate.

        Returns:
            True if the path should be skipped, False otherwise.
        """
        if os.path.islink(path) and not os.path.exists(path):
            try:
                target = os.readlink(path)
                logger.warning("Skipping broken symlink: %s -> %s", path, target)
            except OSError:
                logger.warning("Skipping broken symlink: %s", path)
            return True

        if not os.path.exists(path):
            logger.error("Path does not exist: %s", path)
            return True

        return False

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
            metadata = self._prune_metadata(metadata)

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
        metadata = self._prune_metadata(metadata)

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

    @staticmethod
    def _normalize_markdown_headers(levels: Optional[object]) -> list[tuple[str, str]]:
        """
        Normalize Markdown header configuration into (separator, label) pairs.
        """
        if levels is None:
            return [("#", "Header 1"), ("##", "Header 2"), ("###", "Header 3")]

        if isinstance(levels, dict):
            normalized: list[tuple[str, str]] = []
            for header, label in levels.items():
                header_str = str(header)
                label_str = label if isinstance(label, str) else f"Header Level {label}"
                normalized.append((header_str, label_str))
            return normalized

        if isinstance(levels, (list, tuple)):
            normalized = []
            for entry in levels:
                if not isinstance(entry, (list, tuple)) or len(entry) != 2:
                    raise ValueError(
                        "markdown_levels entries must be (separator, label) pairs."
                    )
                header, label = entry
                normalized.append((str(header), str(label)))
            return normalized

        raise TypeError(
            "markdown_levels must be None, a dict mapping header tokens, or a sequence "
            "of (separator, label) pairs."
        )

    def _build_text_splitter(
        self,
        strategy: SplitterStrategy,
        chunk_size: int,
        chunk_overlap: int,
        tokenizer_model_name: str,
        markdown_levels: Sequence[tuple[str, str]],
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

    @staticmethod
    def _prune_metadata(metadata: dict) -> dict:
        """
        Drop metadata entries that are empty, blank, or None to satisfy strict vector stores.
        """
        cleaned: dict = {}
        for key, value in metadata.items():
            if value is None:
                continue
            if isinstance(value, str):
                if not value.strip():
                    continue
                lower_key = key.lower()
                if lower_key.endswith("date"):
                    coerced = IngestionPipeline._coerce_datetime(value)
                    if not coerced:
                        continue
                    cleaned[key] = coerced
                    continue
            if isinstance(value, (list, tuple, set)) and not any(item for item in value):
                continue
            cleaned[key] = value
        return cleaned

    @staticmethod
    def _coerce_datetime(raw: str) -> Optional[str]:
        """
        Try to coerce various date representations into RFC3339 strings.
        """
        text = raw.strip()
        if not text:
            return None

        # Normalize common timezone shorthands
        if text.endswith("Z"):
            candidate = text[:-1] + "+00:00"
        else:
            candidate = text

        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
            try:
                dt = datetime.strptime(candidate, fmt)
                dt = dt.replace(tzinfo=timezone.utc)
                return dt.isoformat()
            except ValueError:
                continue

        # Attempt ISO parsing with timezone information
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            pass

        # PDF timestamp format: D:YYYYMMDDHHmmSS[Z+-offset]
        m = re.match(r"^D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?([Zz]|[+-]\d{2}'?\d{2}')?$", text)
        if m:
            parts = m.groups()
            y = int(parts[0])
            month = int(parts[1] or "1")
            day = int(parts[2] or "1")
            hour = int(parts[3] or "0")
            minute = int(parts[4] or "0")
            second = int(parts[5] or "0")
            tz_raw = parts[6] or "Z"
            if tz_raw.upper() == "Z":
                tz = timezone.utc
            elif re.match(r"[+-]\d{2}'?\d{2}'?", tz_raw):
                sign = 1 if tz_raw.startswith("+") else -1
                digits = re.sub(r"[+'-]", "", tz_raw)
                offset_hours = int(digits[:2])
                offset_minutes = int(digits[2:4]) if len(digits) >= 4 else 0
                tz = timezone(sign * timedelta(hours=offset_hours, minutes=offset_minutes))
            else:
                tz = timezone.utc
            try:
                dt = datetime(y, month, day, hour, minute, second, tzinfo=tz)
                return dt.isoformat()
            except ValueError:
                return None

        return None

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
