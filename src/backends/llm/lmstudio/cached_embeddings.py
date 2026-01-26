"""
Cached Embedding Service with SQLite support for massive re-ingestion speedups.
"""

import hashlib
import json
import time
from typing import List, Optional, Any

from src import logger
from src.backends.storage.sqlite.manager import get_sqlite_manager


class CachedEmbeddingService:
    """
    Wrapper around EmbeddingService that adds SQLite-based caching.
    """

    def __init__(
        self,
        embedding_service: Any,
        enabled: bool = True,
        ttl_seconds: int = 604800,  # 7 days default
        key_prefix: str = "embed:",
    ):
        self.embedding_service = embedding_service
        self.enabled = enabled
        self.ttl_seconds = ttl_seconds
        self.key_prefix = key_prefix

        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_errors = 0

        self.sqlite_manager = get_sqlite_manager()
        self.control_plane = self.sqlite_manager.control_plane

        if not self.enabled:
            logger.info("Embedding cache is DISABLED")
        else:
            logger.info(
                "Embedding cache is ENABLED (SQLite, prefix='%s', ttl=%ds)",
                self.key_prefix,
                self.ttl_seconds,
            )

    def _compute_cache_key(self, text: str, source: Optional[str] = None, chunk_index: Optional[int] = None) -> str:
        if source and chunk_index is not None:
            composite = f"{source}::{chunk_index}::{text}"
            text_hash = hashlib.sha256(composite.encode("utf-8")).hexdigest()
        else:
            text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

        return f"{self.key_prefix}{text_hash}"

    def _purge_expired(self) -> None:
        if not self.enabled:
            return
        now_ts = int(time.time())
        with self.control_plane.get_connection() as conn:
            conn.execute(
                "DELETE FROM embedding_cache WHERE expires_at <= ?",
                (now_ts,),
            )

    def _get_from_cache(self, cache_key: str) -> Optional[List[float]]:
        if not self.enabled:
            return None

        try:
            self._purge_expired()
            with self.control_plane.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT embedding_json FROM embedding_cache WHERE cache_key = ?",
                    (cache_key,),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                embedding = json.loads(row[0])
                if not isinstance(embedding, list):
                    return None
                self._cache_hits += 1
                return embedding
        except Exception as exc:
            self._cache_errors += 1
            logger.warning("Cache retrieval error for key %s: %s", cache_key[:20], exc)
            return None

    def _store_in_cache(self, cache_key: str, embedding: List[float]) -> None:
        if not self.enabled:
            return

        try:
            payload = json.dumps(embedding)
            expires_at = int(time.time()) + int(self.ttl_seconds)
            with self.control_plane.get_connection() as conn:
                conn.execute(
                    """
                    INSERT INTO embedding_cache (cache_key, embedding_json, expires_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        embedding_json = excluded.embedding_json,
                        expires_at = excluded.expires_at
                    """,
                    (cache_key, payload, expires_at),
                )
        except Exception as exc:
            self._cache_errors += 1
            logger.warning("Cache storage error for key %s: %s", cache_key[:20], exc)

    def generate(self, text: str, source: Optional[str] = None, chunk_index: Optional[int] = None) -> List[float]:
        cache_key = self._compute_cache_key(text, source, chunk_index)

        cached_embedding = self._get_from_cache(cache_key)
        if cached_embedding is not None:
            if self._cache_hits % 100 == 0:
                self.log_stats()
            return cached_embedding

        self._cache_misses += 1
        embedding = self.embedding_service.generate(text)
        self._store_in_cache(cache_key, embedding)

        total_requests = self._cache_hits + self._cache_misses
        if total_requests % 1000 == 0:
            self.log_stats()

        return embedding

    def generate_batch(
        self,
        texts: List[str],
        sources: Optional[List[Optional[str]]] = None,
        chunk_indices: Optional[List[Optional[int]]] = None,
    ) -> List[List[float]]:
        if not texts:
            return []

        if sources is None:
            sources = [None] * len(texts)
        if chunk_indices is None:
            chunk_indices = [None] * len(texts)

        cache_keys = [
            self._compute_cache_key(text, source, chunk_idx)
            for text, source, chunk_idx in zip(texts, sources, chunk_indices)
        ]
        results: List[Optional[List[float]]] = [None] * len(texts)
        texts_to_generate: List[tuple[int, str]] = []

        for idx, (text, cache_key) in enumerate(zip(texts, cache_keys)):
            cached_embedding = self._get_from_cache(cache_key)
            if cached_embedding is not None:
                results[idx] = cached_embedding
            else:
                texts_to_generate.append((idx, text))

        if texts_to_generate:
            self._cache_misses += len(texts_to_generate)
            texts_for_generation = [text for _, text in texts_to_generate]

            if hasattr(self.embedding_service, "generate_batch"):
                generated_embeddings = self.embedding_service.generate_batch(texts_for_generation)
            else:
                generated_embeddings = [self.embedding_service.generate(text) for text in texts_for_generation]

            for (original_idx, _), embedding in zip(texts_to_generate, generated_embeddings):
                cache_key = cache_keys[original_idx]
                self._store_in_cache(cache_key, embedding)
                results[original_idx] = embedding

        return [emb for emb in results if emb is not None]

    def get_stats(self) -> dict:
        total = self._cache_hits + self._cache_misses
        hit_rate = (self._cache_hits / total * 100) if total > 0 else 0.0
        return {
            "enabled": self.enabled,
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "cache_errors": self._cache_errors,
            "hit_rate_pct": hit_rate,
            "total_requests": total,
        }

    def log_stats(self) -> None:
        stats = self.get_stats()
        if stats["total_requests"] > 0:
            logger.info(
                "Embedding cache stats: hits=%d, misses=%d, errors=%d, hit_rate=%.1f%%",
                stats["cache_hits"],
                stats["cache_misses"],
                stats["cache_errors"],
                stats["hit_rate_pct"],
            )

    def reset_stats(self) -> None:
        self._cache_hits = 0
        self._cache_misses = 0
        self._cache_errors = 0


__all__ = ["CachedEmbeddingService"]
