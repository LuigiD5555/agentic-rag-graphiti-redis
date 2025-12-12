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
from typing import Iterable, List, Optional, Dict, Callable, Any, cast, Set, Tuple
try:
    import tiktoken  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    tiktoken = None

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
from src.ingestion.loaders import (
    CODE_LOADER_SPECS,
    TEXT_LOADER_SPECS,
    PlainTextLoader,
)
from src.ingestion.catalog import IngestionCatalog
from src import logger
from src.ingestion.loaders.errors import LoaderError


class SplitterStrategy(str, Enum):
    """Available text splitting strategies."""
    TOKEN = "token"                  # token-aware via tiktoken (recommended default)
    RECURSIVE = "recursive"          # character-based, robust generic splitter
    MARKDOWN_HEADERS = "md_headers"  # respects Markdown header hierarchy
    SEMANTIC = "semantic"            # embeddings-based (experimental)


CATALOG_PATH = os.environ.get(
    "INGESTION_CATALOG_PATH",
    os.path.join("data", "ingestion_catalog.json"),
)


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
        self.catalog = IngestionCatalog(CATALOG_PATH)
        self._observed_files: Set[str] = set()
        self._observed_directories: Set[str] = set()
        self._file_context: Dict[str, Optional[Any]] = {}
        self._current_file_info: Optional[Dict[str, Any]] = None
        self._file_context: Dict[str, Optional[Any]] = {
            "file_index": None,
            "total_files": None,
            "directory_path": None,
        }
        self.embedding_token_limit = max(0, getattr(options, "embedding_token_limit", 0))
        self._embedding_effective_limit = self._effective_limit(self.embedding_token_limit)

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
        self._observed_files = set()
        self._observed_directories = set()
        try:
            for path in paths:
                abs_path = os.path.abspath(path)
                if self._should_skip_path(abs_path):
                    continue

                if os.path.isfile(abs_path):
                    directory = os.path.dirname(abs_path) or os.path.abspath(".")
                    self._record_directory_listing(directory, [abs_path])
                    self._process_candidate_file(
                        abs_path,
                        file_index=1,
                        total_files=1,
                        directory_path=directory,
                    )
                    continue

                for root, _, files in os.walk(abs_path):
                    sorted_files = sorted(files)
                    full_paths = [os.path.join(root, name) for name in sorted_files]
                    self._record_directory_listing(root, full_paths)
                    for index, filename in enumerate(sorted_files, start=1):
                        full_path = os.path.join(root, filename)
                        self._process_candidate_file(
                            full_path,
                            file_index=index,
                            total_files=len(sorted_files),
                            directory_path=root,
                        )
        finally:
            self._finalize_ingestion_run()

    def _process_candidate_file(
        self,
        full_path: str,
        *,
        file_index: Optional[int] = None,
        total_files: Optional[int] = None,
        directory_path: Optional[str] = None,
    ) -> None:
        """
        Dispatch a file to the appropriate loader if supported.

        Args:
            full_path: Absolute path to the file.
        """
        if self._should_skip_path(full_path):
            return

        directory = directory_path or os.path.dirname(full_path)
        file_info = self._gather_file_metadata(full_path)
        self._register_observed_file(full_path)

        if not self.catalog.should_process_file(file_info):
            logger.info("Skipping %s; no changes detected.", full_path)
            self._current_file_info = None
            return

        self._file_context = {
            "file_index": file_index,
            "total_files": total_files,
            "directory_path": directory,
        }
        self._current_file_info = file_info
        logger.info("Processing candidate file: %s", full_path)

        for extensions, loader_cls in TEXT_LOADER_SPECS:
            if full_path.endswith(extensions):
                self._process_text_document(loader_cls(full_path))
                return

        for extensions, loader_cls in CODE_LOADER_SPECS:
            if full_path.endswith(extensions):
                self._process_code_document(loader_cls(full_path))
                return

        self._process_as_plain_text(full_path)

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
        documents: Optional[List[Document]] = self._call_loader(loader, "load")
        if not documents:
            self._current_file_info = None
            return

        chunks = list(self._split_documents(documents))
        if not chunks:
            source = self._resolve_loader_source(loader)
            logger.warning("Skipping %s; no chunks produced after splitting.", source)
            self._current_file_info = None
            return

        prepared_chunks = self._prepare_embedding_segments(chunks, self.embedding_token_limit)
        if not prepared_chunks:
            source = self._resolve_loader_source(loader)
            logger.warning(
                "Skipping %s; splitting produced no embedding-ready chunks.", source
            )
            self._current_file_info = None
            return

        chunk_total = len(prepared_chunks)
        source = self._resolve_loader_source(loader)
        file_info = self._current_file_info or self._gather_file_metadata(source)
        file_context = getattr(self, "_file_context", {}) or {}
        directory_file_index = file_context.get("file_index")
        directory_total_files = file_context.get("total_files")
        directory_path = file_context.get("directory_path") or file_info.get("parent_directory")
        ingested_at = datetime.now(timezone.utc).isoformat()

        # 2) Split into chunks with your existing strategy (and optional segmenting)
        for chunk_index, (segment_text, chunk_meta) in enumerate(prepared_chunks, start=1):
            # --- Sanitize and hash content (idempotency key) ---
            sanitized_text: str = self._sanitize_text(segment_text)
            sanitized_text = self._truncate_to_token_limit(
                sanitized_text,
                self._embedding_effective_limit,
                self.tokenizer_model_name,
            )
            content_hash: str = self._generate_hash(sanitized_text)

            # Skip duplicates quickly
            if self._vector_store_contains(content_hash):
                continue

            # 3) Generate embedding once per chunk
            embedding = self.embedding_service.generate(sanitized_text)

            # 4) Build SAFE metadata strictly from a whitelist.
            #    DO NOT trust arbitrary keys from chunk.metadata (e.g., XMP tags).
            raw_meta: Dict[str, Any] = dict(chunk_meta or {})

            # Only include fields explicitly supported by your Weaviate schema.
            # Coerce types defensively to match schema expectations.
            source_value = str(raw_meta.get("source") or file_info.get("file_path") or "document")
            safe_metadata: Dict[str, Any] = {
                "content": sanitized_text,                               # str
                "source": source_value,                                  # str
                "visibility": str(self.visibility),                      # str
                "owner_id": str(self.owner_id),                          # str
                "allowed_user_ids": [str(u) for u in (self.allowed_user_ids or [])],  # list[str]
                "hash": content_hash,                                    # str
                "file_path": file_info.get("file_path"),
                "file_name": file_info.get("file_name"),
                "file_extension": file_info.get("file_extension"),
                "parent_directory": directory_path,
                "file_size_bytes": file_info.get("file_size_bytes"),
                "file_modified_at": file_info.get("file_modified_at"),
                "file_id": file_info.get("file_id"),
                "chunk_index": chunk_index,
                "chunk_total": chunk_total,
                "ingested_at": ingested_at,
                "directory_file_index": directory_file_index,
                "directory_total_files": directory_total_files,
                "archived": False,
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

        self._finalize_file_ingestion(file_info, chunk_total)

    def _process_code_document(self, code_loader) -> None:
        """
        Load and process a code-based document.

        Args:
            code_loader: A code structure loader instance with `load_structure_summary() -> str`.
        """
        summary_text_raw = self._call_loader(code_loader, "load_structure_summary")
        if not summary_text_raw:
            self._current_file_info = None
            return

        summary_text = self._sanitize_text(summary_text_raw)
        summary_hash = self._generate_hash(summary_text)
        file_info = self._current_file_info or self._gather_file_metadata(getattr(code_loader, "path", None))

        if self._vector_store_contains(summary_hash):
            self._finalize_file_ingestion(file_info, chunk_total=1)
            return

        embedding = self.embedding_service.generate(summary_text)
        file_context = getattr(self, "_file_context", {}) or {}
        ingested_at = datetime.now(timezone.utc).isoformat()

        metadata = {
            "type": "code_context",
            "structure_summary": summary_text,
            "visibility": self.visibility,
            "owner_id": self.owner_id,
            "allowed_user_ids": self.allowed_user_ids,
            "hash": summary_hash,
            "file_path": file_info.get("file_path"),
            "file_name": file_info.get("file_name"),
            "file_extension": file_info.get("file_extension"),
            "parent_directory": file_context.get("directory_path") or file_info.get("parent_directory"),
            "file_size_bytes": file_info.get("file_size_bytes"),
            "file_modified_at": file_info.get("file_modified_at"),
            "file_id": file_info.get("file_id"),
            "directory_file_index": file_context.get("file_index"),
            "directory_total_files": file_context.get("total_files"),
            "ingested_at": ingested_at,
            "archived": False,
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

        self._finalize_file_ingestion(file_info, chunk_total=1)

    def _process_as_plain_text(self, path: str) -> None:
        """
        Fallback handler: attempt to ingest any remaining file as plain text.

        Some extensions may not have a dedicated loader; rather than skipping them
        outright we try a simple text read to honor the user's request.
        """
        self._process_text_document(PlainTextLoader(path))

    # ---------- helpers ----------

    def _record_directory_listing(self, directory_path: str, file_paths: Iterable[str]) -> None:
        directory = os.path.abspath(directory_path)
        self.catalog.record_directory(directory, file_paths)
        self._observed_directories.add(directory)

    def _register_observed_file(self, full_path: str) -> None:
        self._observed_files.add(os.path.abspath(full_path))

    def _finalize_file_ingestion(self, file_info: Dict[str, Any], chunk_total: int) -> None:
        directory_total = None
        if isinstance(self._file_context, dict):
            directory_total = self._file_context.get("total_files")
        self.catalog.record_file_ingestion(
            file_info,
            chunk_total=chunk_total,
            directory_total=directory_total,
        )
        self._current_file_info = None

    def _finalize_ingestion_run(self) -> None:
        try:
            self._handle_deleted_files()
        finally:
            self.catalog.save()

    def _handle_deleted_files(self) -> None:
        missing = self.catalog.list_missing_files(
            self._observed_files,
            self._observed_directories,
        )
        if not missing:
            return
        archive_fn = getattr(self.vector_store, "archive_file", None)
        if not callable(archive_fn):
            for entry in missing:
                logger.warning("Archiving unsupported; leaving stale embeddings for %s", entry["file_path"])
            return

        for entry in missing:
            file_id = entry.get("file_id")
            file_path = entry.get("file_path")
            if not file_id:
                continue
            try:
                archive_fn(file_id, tenant_id=self.tenant_id)  # type: ignore[arg-type]
                self.catalog.mark_archived(file_path)
                logger.info("Archived embeddings for removed file %s", file_path)
            except Exception as exc:  # pragma: no cover - defensive
                logger.error("Failed to archive embeddings for %s: %s", file_path, exc)

    def _gather_file_metadata(self, path: Optional[str]) -> Dict[str, Any]:
        """
        Collect filesystem metadata for a given source path.
        """
        resolved = str(path or "").strip()
        if not resolved and hasattr(path, "strip"):
            resolved = str(path).strip()

        info: Dict[str, Any] = {
            "file_path": resolved or None,
            "file_name": os.path.basename(resolved) if resolved else None,
            "file_extension": os.path.splitext(resolved)[1].lower() if resolved else None,
            "parent_directory": os.path.dirname(resolved) if resolved else None,
            "file_size_bytes": None,
            "file_modified_at": None,
            "file_id": self._generate_hash(resolved) if resolved else None,
        }

        if resolved and os.path.isfile(resolved):
            try:
                stats = os.stat(resolved)
                info["file_size_bytes"] = stats.st_size
                info["file_modified_at"] = datetime.fromtimestamp(
                    stats.st_mtime, tz=timezone.utc
                ).isoformat()
            except OSError:
                pass

        return info

    def _call_loader(self, loader: object, method_name: str):
        """
        Execute a loader method with uniform error handling.

        Returns:
            The result of the loader call, or None if it failed.
        """
        load_fn = getattr(loader, method_name, None)

        if load_fn is None:
            logger.error(
                "Loader %s does not implement %s; skipping.",
                loader.__class__.__name__,
                method_name,
            )
            return None

        try:
            return load_fn()
        except LoaderError as exc:
            self._log_loader_skip(loader, exc)
        except Exception as exc:  # pragma: no cover - defensive logging
            self._log_loader_error(loader, exc)

        return None

    def _log_loader_skip(self, loader: object, exc: Exception) -> None:
        """Log a warning when a loader intentionally skips a file."""
        source = self._resolve_loader_source(loader)
        logger.warning("Skipping %s: %s", source, exc)
        self._record_failure(source, str(exc), reason="loader_skip")

    def _log_loader_error(self, loader: object, exc: Exception) -> None:
        """Log unexpected loader failures."""
        source = self._resolve_loader_source(loader)
        logger.exception(
            "Loader %s failed for %s: %s",
            loader.__class__.__name__,
            source,
            exc,
        )
        self._record_failure(source, str(exc), reason="loader_error")

    @staticmethod
    def _resolve_loader_source(loader: object) -> str:
        """Attempt to resolve the source path associated with a loader."""
        for attr in ("path", "_path", "file_path", "source"):
            value = getattr(loader, attr, None)
            if value:
                return str(value)
        return loader.__class__.__name__

    def _record_failure(self, source: str, message: str, reason: str) -> None:
        """Record metadata for a file that could not be ingested."""
        file_info = self._gather_file_metadata(source)
        file_context = getattr(self, "_file_context", {}) or {}
        record = {
            "source": source,
            "file_path": file_info.get("file_path"),
            "file_name": file_info.get("file_name"),
            "file_extension": file_info.get("file_extension"),
            "parent_directory": file_context.get("directory_path") or file_info.get("parent_directory"),
            "file_size_bytes": file_info.get("file_size_bytes"),
            "file_modified_at": file_info.get("file_modified_at"),
            "file_id": file_info.get("file_id"),
            "failure_reason": reason,
            "failure_message": message,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "directory_file_index": file_context.get("file_index"),
            "directory_total_files": file_context.get("total_files"),
        }
        sink = getattr(self.vector_store, "upsert_failure", None)
        if callable(sink):
            sink(record)
        else:  # pragma: no cover - defensive fallback
            logger.warning("Failure record (no sink available): %s", record)

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

    def _prepare_embedding_segments(
        self,
        chunks: List["Document"],
        limit: int,
    ) -> List[Tuple[str, Dict[str, Any]]]:
        """
        Optionally split oversized chunks into smaller segments before embedding.

        A simple whitespace token count is used to avoid blowing past the embedding
        model's context window. When limit <= 0 no additional splitting occurs.
        """
        effective_limit = self._effective_limit(limit)
        if effective_limit <= 0:
            return [
                (chunk.page_content or "", dict(getattr(chunk, "metadata", {}) or {}))
                for chunk in chunks
            ]

        segments: List[Tuple[str, Dict[str, Any]]] = []
        for chunk in chunks:
            content = chunk.page_content or ""
            metadata = dict(getattr(chunk, "metadata", {}) or {})
            tokens = content.split()
            if not tokens:
                segments.append((content, metadata))
                continue
            if len(tokens) <= effective_limit:
                segments.append((content, metadata))
                continue

            segments_created = 0
            start = 0
            while start < len(tokens):
                end = min(start + effective_limit, len(tokens))
                segments.append((" ".join(tokens[start:end]), metadata))
                start = end
                segments_created += 1

            source = metadata.get("source") or metadata.get("file_path") or "document"
            logger.debug(
                "Chunk from %s split into %d segments to honor %d-token embedding limit.",
                source,
                segments_created,
                limit,
            )

        return segments

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

    def _truncate_to_token_limit(self, text: str, limit: int, model_name: Optional[str]) -> str:
        """
        Ensure text stays under the embedding token limit with a small safety margin.
        Uses tiktoken when available; otherwise falls back to whitespace tokens.
        """
        if limit <= 0:
            return text

        effective_limit = max(1, limit)

        # For very small limits, prefer whitespace tokens to avoid BPE collisions.
        if effective_limit <= 8 or tiktoken is None:
            tokens = text.split()
            if len(tokens) <= effective_limit:
                return text
            return " ".join(tokens[:effective_limit])

        try:
            enc = tiktoken.encoding_for_model(model_name) if model_name else tiktoken.get_encoding("cl100k_base")
        except Exception:
            enc = tiktoken.get_encoding("cl100k_base")

        token_ids = enc.encode(text)
        if len(token_ids) <= effective_limit:
            return text
        truncated = enc.decode(token_ids[:effective_limit])
        return truncated

    @staticmethod
    def _effective_limit(limit: int) -> int:
        """
        Compute a conservative token cap: trim a margin (~10%, min 8, max 1/3 of limit).
        """
        if limit <= 0:
            return 0
        margin = max(8, int(limit * 0.1))
        margin = min(margin, max(1, limit // 3))
        return max(1, limit - margin)

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
        - file_path: str
        - file_name: str
        - file_extension: str
        - parent_directory: str
        - file_size_bytes: int
        - file_modified_at: str (ISO timestamp)
        - file_id: str
        - chunk_index: int
        - chunk_total: int
        - ingested_at: str (ISO timestamp)
        Any other key (e.g., XMP/EXIF like 'aapl:keywords', 'pdf:Author', 'path', etc.) is dropped.
        """
        allowed_keys = {
            "content",
            "source",
            "visibility",
            "owner_id",
            "allowed_user_ids",
            "hash",
            "file_path",
            "file_name",
            "file_extension",
            "parent_directory",
            "file_size_bytes",
            "file_modified_at",
            "file_id",
            "chunk_index",
            "chunk_total",
            "ingested_at",
            "directory_file_index",
            "directory_total_files",
            "archived",
        }
        pruned: dict = {}

        def _set_str(key: str) -> None:
            value = metadata.get(key)
            if isinstance(value, str):
                pruned[key] = value

        def _set_int(key: str) -> None:
            value = metadata.get(key)
            if isinstance(value, int) and value >= 0:
                pruned[key] = value

        _set_str("content")
        _set_str("source")
        _set_str("visibility")
        _set_str("owner_id")

        value = metadata.get("allowed_user_ids")
        if value is None:
            pass
        elif isinstance(value, list):
            pruned["allowed_user_ids"] = [str(x) for x in value]
        elif isinstance(value, str):
            pruned["allowed_user_ids"] = [value]

        _set_str("hash")
        _set_str("file_path")
        _set_str("file_name")
        _set_str("file_extension")
        _set_str("parent_directory")
        _set_int("file_size_bytes")
        _set_str("file_modified_at")
        _set_str("file_id")
        _set_int("chunk_index")
        _set_int("chunk_total")
        _set_str("ingested_at")
        _set_int("directory_file_index")
        _set_int("directory_total_files")
        value = metadata.get("archived")
        if isinstance(value, bool):
            pruned["archived"] = value

        # Finally, ensure we did not leak any unexpected key
        for key in list(pruned.keys()):
            if key not in allowed_keys:
                pruned.pop(key, None)

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
