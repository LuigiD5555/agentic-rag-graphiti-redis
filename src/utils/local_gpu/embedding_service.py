from __future__ import annotations

import threading
from typing import Iterable, List, Sequence

import torch
from sentence_transformers import SentenceTransformer

from src import logger
from src.rag.interfaces.embedding_interface import EmbeddingInterface


class LocalGPUEmbeddingService(EmbeddingInterface):
    """
    Embedding service that runs sentence-transformers locally using CPU or CUDA.

    This service is thread-safe and exposes both single and batch generation helpers.
    """

    def __init__(self, config: object) -> None:
        model_name = getattr(config, "LOCAL_GPU_EMBED_MODEL", "all-MiniLM-L6-v2")
        requested_device = (getattr(config, "LOCAL_GPU_DEVICE", "cuda") or "cuda").strip()
        batch_size = int(getattr(config, "LOCAL_GPU_BATCH_SIZE", 32) or 32)

        self._device = self._resolve_device(requested_device)
        self._batch_size = max(1, batch_size)
        self._lock = threading.RLock()
        self.model_name = model_name

        try:
            self._model = SentenceTransformer(model_name, device=str(self._device))
        except Exception as exc:  # pragma: no cover (errors are rare but must be surfaced)
            logger.error(
                "Failed to initialize sentence-transformers model %s on %s: %s",
                model_name,
                self._device,
                exc,
            )
            raise

        logger.info(
            "Local GPU embeddings ready (model=%s, device=%s, batch=%d)",
            model_name,
            self._device,
            self._batch_size,
        )

    def generate(self, text: str, **kwargs) -> List[float]:
        """Generate a single embedding vector. Extra kwargs are ignored."""
        if not text:
            text = ""
        return self._encode_texts([text])[0]

    def generate_batch(self, texts: Sequence[str], **kwargs) -> List[List[float]]:
        """Generate embeddings for multiple texts at once."""
        normalized: List[str] = [t or "" for t in texts]
        return self._encode_texts(normalized)

    # ---------- Helpers ----------

    def _encode_texts(self, texts: Sequence[str]) -> List[List[float]]:
        if not texts:
            return []
        with torch.inference_mode():
            with self._lock:
                numpy_embeddings = self._model.encode(
                    texts,
                    batch_size=self._batch_size,
                    convert_to_numpy=True,
                    show_progress_bar=False,
                )
        return [self._vector_to_list(vector) for vector in numpy_embeddings]

    @staticmethod
    def _vector_to_list(vector: Iterable[float]) -> List[float]:
        return [float(value) for value in vector]

    @staticmethod
    def _resolve_device(requested: str) -> torch.device:
        normalized = (requested or "cuda").strip().lower()
        if normalized in {"", "auto", "cuda", "gpu"}:
            if torch.cuda.is_available():
                target = "cuda:0"
            else:
                logger.warning("CUDA requested but torch.cuda.is_available() is False; using CPU")
                target = "cpu"
        else:
            try:
                target = str(torch.device(normalized))
            except Exception as exc:  # pragma: no cover
                logger.warning(
                    "Invalid LOCAL_GPU_DEVICE=%r (%s); falling back to CPU", requested, exc
                )
                target = "cpu"
            else:
                if target.startswith("cuda") and not torch.cuda.is_available():
                    logger.warning(
                        "Requested device %s requires CUDA but torch.cuda.is_available() is False; using CPU",
                        target,
                    )
                    target = "cpu"
        return torch.device(target)
