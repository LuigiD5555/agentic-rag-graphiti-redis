"""
Utility helpers around local GPU embedding services.
"""
from .embedding_service import LocalGPUEmbeddingService
from .factory import build_local_gpu_embedding_service

__all__ = ["LocalGPUEmbeddingService", "build_local_gpu_embedding_service"]
