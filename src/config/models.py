"""
Model auto-selection utilities for LM Studio (OpenAI-compatible).
Uses only `requests` and environment variables already present.
"""

from __future__ import annotations
import os
import requests
from typing import Optional, Dict, Any, List


def list_models(base_url: str, timeout: float = 2.0) -> List[Dict[str, Any]]:
    """Return the /v1/models payload (list). If LM Studio is down, return []."""
    try:
        r = requests.get(f"{base_url.rstrip('/')}/models", timeout=timeout)
        if r.status_code == 200:
            data = r.json()
            # LM Studio returns {"data": [{"id": "..."}...]} format
            return data.get("data", [])
    except Exception:
        pass
    return []


def pick_first_active_model(models: List[Dict[str, Any]]) -> Optional[str]:
    """Pick the first model id if any."""
    for m in models:
        mid = m.get("id") or m.get("name")
        if mid:
            return mid
    return None


def pick_first_embedding_model(models: List[Dict[str, Any]]) -> Optional[str]:
    """
    Heuristic: prefer ids containing 'embed' or 'minilm'.
    Fallback: first model.
    """
    candidates = []
    for m in models:
        mid = m.get("id") or m.get("name") or ""
        lid = mid.lower()
        if "embed" in lid or "minilm" in lid or "nomic" in lid:
            candidates.append(mid)
    return candidates[0] if candidates else pick_first_active_model(models)


def resolve_models_from_env() -> Dict[str, Optional[str]]:
    """
    If LMSTUDIO_CHAT_MODEL / LMSTUDIO_EMBED_MODEL are empty,
    auto-pick from /v1/models.
    """
    base = os.getenv("OPENAI_API_BASE", "http://127.0.0.1:1234/v1")
    chat_env = os.getenv("LMSTUDIO_CHAT_MODEL", "").strip()
    emb_env  = os.getenv("LMSTUDIO_EMBED_MODEL", "").strip()

    models = list_models(base)
    chat_model = chat_env or pick_first_active_model(models)
    embed_model = emb_env or pick_first_embedding_model(models)
    return {"chat": chat_model, "embed": embed_model}
