from src.rag.audit import get_logger, resolve_level
from src.rag.interfaces.vector_interface import SupportsExists, VectorInterface


def vector_store_contains(vector_store: VectorInterface, hash_id: str) -> bool:
    if isinstance(vector_store, SupportsExists):
        httpx_logger = get_logger("httpx")
        previous_level = httpx_logger.level
        httpx_logger.setLevel(resolve_level("WARNING"))
        try:
            return vector_store.exists(hash_id)
        except (AttributeError, NotImplementedError, TypeError):
            return False
        finally:
            httpx_logger.setLevel(previous_level)
    return False


__all__ = ["vector_store_contains"]
