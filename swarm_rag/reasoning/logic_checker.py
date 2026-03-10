"""
Logic Checker — verifies consistency between hypotheses and facts using NLI.

Model: cross-encoder/nli-deberta-v3-small (~220MB, provisional, no fine-tuning)
       Falls back to cross-encoder/nli-deberta-v3-base (~740MB) if small not available.

Strategy (F4, no training needed):
  For each (hypothesis, fact) pair, run NLI to get:
    - 'entailment'   → fact supports hypothesis  (positive signal)
    - 'neutral'      → unrelated
    - 'contradiction' → fact contradicts hypothesis (negative signal)

  Consistency score per hypothesis = (entailments - contradictions) / total_pairs
  Hypotheses with score < threshold are flagged in specialists.conflicts_found.

Fallback (no model): cosine similarity between hypothesis and ranked_evidence
  using sentence-transformers (already loaded by ConfidenceEstimator).
"""
from __future__ import annotations

import logging
import math
from typing import Any, Optional

logger = logging.getLogger(__name__)

_MODEL_SMALL = "cross-encoder/nli-deberta-v3-small"
_MODEL_BASE  = "cross-encoder/nli-deberta-v3-base"
_CONSISTENCY_THRESHOLD = 0.0   # below this → flag as inconsistent
_MAX_PAIRS = 20                # limit NLI calls per query

_model: Optional[Any] = None
_model_tried: bool = False


def _get_model() -> Optional[Any]:
    global _model, _model_tried
    if _model is not None:
        return _model
    if _model_tried:
        return None
    _model_tried = True
    for model_id in (_MODEL_SMALL, _MODEL_BASE):
        try:
            from sentence_transformers import CrossEncoder
            _model = CrossEncoder(model_id)
            logger.info("LogicChecker loaded: %s", model_id)
            return _model
        except Exception as exc:
            logger.warning("Could not load %s: %s", model_id, exc)
    return None


def check_consistency(
    hypotheses: list[str],
    facts: list[dict],
) -> list[dict]:
    """
    Run NLI between hypotheses and top facts.

    Returns list of conflict dicts for hypotheses that are inconsistent:
      {"hypothesis": str, "score": float, "contradicting_facts": list[str]}
    """
    if not hypotheses or not facts:
        return []

    model = _get_model()
    fact_texts = [f.get("fact") or f.get("text", "") for f in facts[:8]]

    if model is not None:
        return _nli_check(model, hypotheses, fact_texts)
    return _cosine_check(hypotheses, fact_texts)


def _nli_check(model, hypotheses: list[str], fact_texts: list[str]) -> list[dict]:
    conflicts: list[dict] = []
    try:
        for hypothesis in hypotheses:
            pairs = [[hypothesis, fact] for fact in fact_texts]
            if len(pairs) > _MAX_PAIRS:
                pairs = pairs[:_MAX_PAIRS]

            # CrossEncoder returns scores in order: contradiction, entailment, neutral
            # (label order depends on model — DeBERTa-NLI uses this order)
            raw_scores = model.predict(pairs)

            n_entail = 0
            n_contra = 0
            contradicting: list[str] = []

            for score_vec, fact_text in zip(raw_scores, fact_texts):
                # score_vec is [contradiction_score, entailment_score, neutral_score]
                if hasattr(score_vec, "__len__") and len(score_vec) == 3:
                    contra_s, entail_s, neutral_s = score_vec
                    if entail_s > contra_s and entail_s > neutral_s:
                        n_entail += 1
                    elif contra_s > entail_s and contra_s > neutral_s:
                        n_contra += 1
                        contradicting.append(fact_text[:150])
                else:
                    # Binary score (entailment probability)
                    if float(score_vec) < 0.4:
                        n_contra += 1
                        contradicting.append(fact_texts[0][:150])

            total = max(n_entail + n_contra, 1)
            consistency = (n_entail - n_contra) / total

            if consistency < _CONSISTENCY_THRESHOLD:
                conflicts.append({
                    "type": "nli_inconsistency",
                    "hypothesis": hypothesis[:200],
                    "consistency_score": round(consistency, 3),
                    "contradicting_facts": contradicting[:3],
                    "description": (
                        f"Hypothesis has consistency={consistency:.2f} "
                        f"({n_entail} supports, {n_contra} contradictions)"
                    ),
                })
    except Exception as exc:
        logger.warning("NLI check failed: %s — skipping logic check", exc)

    return conflicts


def _cosine_check(hypotheses: list[str], fact_texts: list[str]) -> list[dict]:
    """Fallback: cosine similarity. Low similarity → potential inconsistency."""
    try:
        from sentence_transformers import SentenceTransformer
        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        all_texts = hypotheses + fact_texts
        embeddings = model.encode(all_texts, normalize_embeddings=True).tolist()
        h_embs = embeddings[:len(hypotheses)]
        f_embs = embeddings[len(hypotheses):]

        conflicts: list[dict] = []
        for h_text, h_emb in zip(hypotheses, h_embs):
            sims = [_dot(h_emb, f_emb) for f_emb in f_embs]
            avg_sim = sum(sims) / max(len(sims), 1)
            if avg_sim < 0.3:
                conflicts.append({
                    "type": "low_similarity",
                    "hypothesis": h_text[:200],
                    "consistency_score": round(avg_sim, 3),
                    "contradicting_facts": [],
                    "description": f"Hypothesis has low avg similarity ({avg_sim:.2f}) to evidence.",
                })
        return conflicts
    except Exception as exc:
        logger.warning("Cosine fallback also failed: %s", exc)
        return []


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))
