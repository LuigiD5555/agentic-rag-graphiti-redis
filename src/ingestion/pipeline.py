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
from typing import Iterable, List, Optional, Dict, Callable, Any, cast

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
from src.cli.options import PipelineOptions
from src.utils.decorators import timed, logged
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
        options: PipelineOptions,
    ):
        """Initialize the ingestion pipeline with a parameter object."""
        self.embedding_service = embedding_service
        self.vector_store = vector_store
        self.options = options

        self.owner_id = options.owner_id
        self.visibility = options.visibility
        self.allowed_user_ids = list(options.allowed_user_ids)
        self.tenant_id = options.tenant_id

        self.chunk_size = options.chunk_size
        self.chunk_overlap = options.chunk_overlap
        self.splitter_strategy = options.splitter_strategy or SplitterStrategy.TOKEN
        self.tokenizer_model_name = options.tokenizer_model_name
        self.markdown_levels = self._normalize_markdown_headers(options.markdown_levels)
        self.semantic_embeddings = options.semantic_embeddings

        self.text_splitter = self._build_text_splitter(self.splitter_strategy, options)

    # --- Friendly factory to reduce long call sites ---
    @classmethod
    def from_options(
        cls,
        embedding_service: EmbeddingInterface,
        vector_store: VectorInterface,
        options: PipelineOptions,
    ) -> "IngestionPipeline":
        return cls(
            embedding_service=embedding_service,
            vector_store=vector_store,
            options=options,
        )

    @logged("Ingesting candidate paths")
    @timed()
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

        logger.info("Processing candidate file: %s", full_path)

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
        Load and process a text-based document and upsert its chunks into the vector store.

        This implementation *whitelists* metadata keys to avoid passing arbitrary
        document metadata to Weaviate (e.g., 'aapl:keywords', 'pdf:Title', etc.),
        which would violate Weaviate/GraphQL property name rules and cause 4xx/5xx
        errors during insert/update.

        Args:
            loader: A document loader instance exposing `load() -> List[Document]`.
        """
        # 1) Load full documents
        documents: List[Document] = loader.load()

        # 2) Split into chunks with your existing strategy
        for chunk in self._split_documents(documents):
            # --- Sanitize and hash content (idempotency key) ---
            sanitized_text: str = self._sanitize_text(chunk.page_content)
            content_hash: str = self._generate_hash(sanitized_text)

            # Skip duplicates quickly
            if self._vector_store_contains(content_hash):
                continue

            # 3) Generate embedding once per chunk
            embedding = self.embedding_service.generate(sanitized_text)

            # 4) Build SAFE metadata strictly from a whitelist.
            #    DO NOT trust arbitrary keys from chunk.metadata (e.g., XMP tags).
            raw_meta: Dict[str, Any] = dict(getattr(chunk, "metadata", {}) or {})

            # Only include fields explicitly supported by your Weaviate schema.
            # Coerce types defensively to match schema expectations.
            safe_metadata: Dict[str, Any] = {
                "content": sanitized_text,                               # str
                "source": str(raw_meta.get("source") or "document"),     # str
                "visibility": str(self.visibility),                      # str
                "owner_id": str(self.owner_id),                          # str
                "allowed_user_ids": [str(u) for u in (self.allowed_user_ids or [])],  # list[str]
                "hash": content_hash,                                    # str
            }

            # Do NOT add arbitrary metadata keys like 'path' if not in schema.
            # If you need it for debugging, log it instead of sending to Weaviate.
            # self.logger.debug("Chunk path (not sent to DB): %s", getattr(loader, "path", None))

            # Final pruning/validation step (your function should enforce whitelist/regex/types)
            safe_metadata = self._prune_metadata(safe_metadata)

            # 5) Upsert in the vector store. Some repos accept tenant_id kwarg.
            try:
                self.vector_store.upsert(
                    content_hash,
                    embedding,
                    safe_metadata,
                    tenant_id=self.tenant_id,  # type: ignore[arg-type]
                )
            except TypeError:
                # Fallback for vector stores that don't accept tenant_id as a kwarg
                self.vector_store.upsert(
                    content_hash,
                    embedding,
                    safe_metadata,
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
        metadata.setdefault("path", getattr(code_loader, "path", None))
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
        options: PipelineOptions,
    ):
        """Factory that returns a modern text splitter instance using registered strategies."""

        builders: Dict[SplitterStrategy, Callable[[], object]] = {
            SplitterStrategy.TOKEN: lambda: TokenTextSplitter(
                chunk_size=options.chunk_size,
                chunk_overlap=options.chunk_overlap,
                model_name=options.tokenizer_model_name,
            ),
            SplitterStrategy.RECURSIVE: lambda: RecursiveCharacterTextSplitter(
                chunk_size=options.chunk_size,
                chunk_overlap=options.chunk_overlap,
            ),
            SplitterStrategy.MARKDOWN_HEADERS: lambda: MarkdownHeaderTextSplitter(
                headers_to_split_on=self.markdown_levels,
            ),
        }

        if SemanticChunker is not None:
            builders[SplitterStrategy.SEMANTIC] = lambda: self._build_semantic_splitter(options)

        builder = builders.get(strategy)
        if builder is None:
            raise ValueError(f"Unknown splitting strategy: {strategy}")
        return builder()

    def _build_semantic_splitter(self, options: PipelineOptions):
        """
        Build a text splitter. If semantic chunking is requested, use SemanticChunker.
        Otherwise fall back to fixed-size chunking.
        """
        # Ensure the experimental SemanticChunker is available at runtime.
        if SemanticChunker is None:
            raise RuntimeError(
                "SemanticChunker is not available; install langchain_experimental to use semantic splitting."
            )

        embeddings = options.semantic_embeddings
        if embeddings is None:
            raise ValueError("options.semantic_embeddings must be provided to build a SemanticChunker.")

        # Cast both the class and the embeddings to Any to satisfy static type checkers
        return cast(Any, SemanticChunker)(
            cast(Any, embeddings),
            breakpoint_threshold_type="percentile",  # 'percentile'|'standard_deviation'|'interquartile'|'gradient'
            buffer_size=options.chunk_overlap,       # window between sentences
            # Optional: control max number of chunks to produce
            number_of_chunks=getattr(options, "number_of_chunks", None),
            # Optional: tuning threshold (0–100 if using 'percentile')
            breakpoint_threshold_amount=getattr(options, "breakpoint_threshold_amount", None),
            add_start_index=True,
        )

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

    # TODO: refactor this metod to another using less if/else statements
    def _prune_metadata(self, metadata: dict) -> dict:
        """
        Keep only properties that exist in the Weaviate class schema and coerce types.

        Allowed keys correspond to RAGDocument schema:
        - content: str
        - source: str
        - visibility: str
        - owner_id: str
        - allowed_user_ids: list[str]
        - hash: str
        Any other key (e.g., XMP/EXIF like 'aapl:keywords', 'pdf:Author', 'path', etc.) is dropped.
        """
        allowed_keys = {
            "content",
            "source",
            "visibility",
            "owner_id",
            "allowed_user_ids",
            "hash",
        }
        pruned: dict = {}

        # content
        value = metadata.get("content")
        if isinstance(value, str):
            pruned["content"] = value

        # source
        value = metadata.get("source")
        if isinstance(value, str):
            pruned["source"] = value

        # visibility
        value = metadata.get("visibility")
        if isinstance(value, str):
            pruned["visibility"] = value

        # owner_id
        value = metadata.get("owner_id")
        if isinstance(value, str):
            pruned["owner_id"] = value

        # allowed_user_ids
        value = metadata.get("allowed_user_ids")
        if value is None:
            pass
        elif isinstance(value, list):
            pruned["allowed_user_ids"] = [str(x) for x in value]
        elif isinstance(value, str):
            pruned["allowed_user_ids"] = [value]
        else:
            # drop invalid types
            pass

        # hash
        value = metadata.get("hash")
        if isinstance(value, str):
            pruned["hash"] = value

        # Finally, ensure we did not leak any unexpected key
        for k in list(pruned.keys()):
            if k not in allowed_keys:
                pruned.pop(k, None)

        return pruned

    @staticmethod
    def _coerce_datetime(raw: str) -> Optional[str]:
        """Try to coerce various date representations into RFC3339 strings."""
        text = raw.strip()
        if not text:
            return None

        candidate = text[:-1] + "+00:00" if text.endswith("Z") else text

        coerced = IngestionPipeline._coerce_by_strptime(candidate)
        if coerced:
            return coerced

        coerced = IngestionPipeline._coerce_by_iso(candidate)
        if coerced:
            return coerced

        coerced = IngestionPipeline._coerce_pdf_timestamp(text)
        if coerced:
            return coerced

        return None

    @staticmethod
    def _coerce_by_strptime(candidate: str) -> Optional[str]:
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
            try:
                dt = datetime.strptime(candidate, fmt)
                dt = dt.replace(tzinfo=timezone.utc)
                return dt.isoformat()
            except ValueError:
                continue
        return None

    @staticmethod
    def _coerce_by_iso(candidate: str) -> Optional[str]:
        try:
            dt = datetime.fromisoformat(candidate)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.isoformat()
        except ValueError:
            return None

    @staticmethod
    def _coerce_pdf_timestamp(text: str) -> Optional[str]:
        # PDF timestamp format: D:YYYYMMDDHHmmSS[Z+-offset]
        m = re.match(r"^D:(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?([Zz]|[+-]\d{2}'?\d{2}')?$", text)
        if not m:
            return None
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
