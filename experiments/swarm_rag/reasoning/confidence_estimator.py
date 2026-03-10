"""
Confidence Estimator — scores how well the evidence supports the query.

Strategy (F3, no fine-tuning needed):
  Cosine similarity between the query embedding and each piece of ranked evidence.
  Confidence = weighted average of top-N similarities, adjusted for:
  - Number of corroborating evidence items (more = higher confidence)
  - Presence of version conflicts (reduces confidence)
  - Whether ranked_evidence is empty (confidence = 0)

Uses sentence-transformers/all-MiniLM-L6-v2 (already loaded by KeyBERT/EvidenceRanker).
Falls back to a heuristic count-based score if model unavailable.
"""
from __future__ import annotations

import logging
import math
from typing import Optional, Any, ClassVar

logger = logging.getLogger(__name__)

_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
_model: Optional[Any] = None
_model_tried: bool = False


def _get_model():
    global _model, _model_tried
    if _model is not None:
        return _model
    if _model_tried:
        return None
    _model_tried = True
    try:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer(_MODEL_ID)
        logger.info("ConfidenceEstimator loaded: %s", _MODEL_ID)
    except Exception as exc:
        logger.warning("ConfidenceEstimator: could not load model: %s — using heuristic", exc)
    return _model


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def estimate_confidence(
    query: str,
    ranked_evidence: list[dict],
    version_conflicts: list[dict],
) -> float:
    """
    Return a confidence score in [0.0, 1.0].

    Args:
        query:            Original or rewritten user query.
        ranked_evidence:  Output of EvidenceRanker (sorted by relevance).
        version_conflicts: Conflicts detected by VersionMonitor.
    """
    if not ranked_evidence:
        return 0.0

    model = _get_model()

    if model is not None:
        score = _semantic_confidence(model, query, ranked_evidence)
    else:
        score = _heuristic_confidence(ranked_evidence)

    # Penalize for version conflicts (each conflict reduces confidence)
    conflict_penalty = min(len(version_conflicts) * 0.1, 0.3)
    score = max(0.0, score - conflict_penalty)

    return round(score, 3)


def _semantic_confidence(model, query: str, evidence: list[dict]) -> float:
    """Cosine similarity between query and top-5 evidence items."""
    try:
        texts = [e.get("fact") or e.get("text", "") for e in evidence[:5]]
        all_texts = [query] + texts
        embeddings = model.encode(all_texts, normalize_embeddings=True).tolist()
        q_emb = embeddings[0]
        similarities = [_cosine(q_emb, e_emb) for e_emb in embeddings[1:]]
        if not similarities:
            return 0.0
        # Weighted average: first evidence item counts more
        weights = [1.0 / (i + 1) for i in range(len(similarities))]
        total_w = sum(weights)
        weighted = sum(s * w for s, w in zip(similarities, weights)) / total_w
        return float(weighted)
    except Exception as exc:
        logger.warning("Semantic confidence failed: %s — using heuristic", exc)
        return _heuristic_confidence(evidence)


def _heuristic_confidence(evidence: list[dict]) -> float:
    """Simple heuristic: average of existing relevance scores, capped at 0.85."""
    scores = [e.get("score", 0.0) for e in evidence[:10] if isinstance(e.get("score"), (int, float))]
    if not scores:
        return 0.2
    avg = sum(scores) / len(scores)
    # More items = slightly more confidence (up to a cap)
    count_bonus = min(len(scores) * 0.02, 0.15)
    return min(avg + count_bonus, 0.85)
