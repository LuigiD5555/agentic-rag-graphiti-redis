"""
Model auto-selection utilities for LM Studio (OpenAI-compatible).
Uses centralized settings instead of environment variables.
"""

import json
import requests
from typing import Optional, Dict, Any, List

from src.conf import settings


def list_models(base_url: str, timeout: float = 2.0) -> List[Dict[str, Any]]:
    """Return the /v1/models payload (list). If LM Studio is down, return []."""
    try:
        r = requests.get(f"{base_url.rstrip('/')}/models", timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            # LM Studio returns {"data": [{"id": "..."}...]} format
            return data.get("data", [])
    except requests.RequestException as exc:
        # LM Studio not reachable / network failure.
        return []
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        # Malformed JSON or unexpected schema.
        return []
    return []


def is_embedding_model(model_id: str) -> bool:
    """Check if a model is an embedding model based on its ID."""
    lid = model_id.lower()
    embedding_keywords = ["embed", "embedding", "minilm", "bge", "nomic", "paraphrase"]
    return any(keyword in lid for keyword in embedding_keywords)


def pick_first_active_model(models: List[Dict[str, Any]]) -> Optional[str]:
    """Pick the first non-embedding model id if any."""
    for m in models:
        mid = m.get("id") or m.get("name")
        if mid and not is_embedding_model(mid):
            return mid
    return None


def pick_first_embedding_model(models: List[Dict[str, Any]]) -> Optional[str]:
    """
    Pick the first embedding model based on keywords in the model ID.
    Fallback: None (no chat model should be used as embedding model).
    """
    for m in models:
        mid = m.get("id") or m.get("name") or ""
        if mid and is_embedding_model(mid):
            return mid
    return None


def resolve_models_from_env() -> Dict[str, Optional[str]]:
    """
    If LMSTUDIO_CHAT_MODEL / LMSTUDIO_EMBED_MODEL are empty,
    auto-pick from /v1/models.
    """
    base = settings.OPENAI_API_BASE
    chat_env = (settings.LMSTUDIO_CHAT_MODEL or "").strip()
    emb_env = (settings.LMSTUDIO_EMBED_MODEL or "").strip()

    models = list_models(base)
    chat_model = chat_env or pick_first_active_model(models)
    embed_model = emb_env or pick_first_embedding_model(models)
    return {"chat": chat_model, "embed": embed_model}
