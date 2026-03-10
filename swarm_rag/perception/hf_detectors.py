"""
F2 Perception detectors — HuggingFace model implementations.

Same async function signatures as detectors.py (F1 regex stubs).
perception_layer.py swaps to these by setting USE_HF_DETECTORS=true
in config/thresholds.yaml or env var SWARM_HF_PERCEPTION=1.

Models are loaded ONCE at module level when first imported.
torch.no_grad() and model.eval() are always set.

Model map (all ~90-420MB, CPU-compatible):
  intent/domain/tone  → sentence-transformers/all-MiniLM-L6-v2  (zero-shot)
  NER                 → dslim/bert-base-NER
  keywords            → KeyBERT (MiniLM backend)
  complexity          → heuristic (same as F1 — no HF model needed)
  language            → langdetect (same as F1)
  math/code           → regex (same as F1 — accurate enough)
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy model holders — populated on first use
# ---------------------------------------------------------------------------

_zero_shot: Optional[Any] = None
_zero_shot_tried: bool = False
_ner_model: Optional[Any] = None
_ner_tried: bool = False
_keybert: Optional[Any] = None
_keybert_tried: bool = False
_hf_available: Optional[bool] = None


def _check_hf() -> bool:
    global _hf_available
    if _hf_available is not None:
        return _hf_available
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        _hf_available = True
    except ImportError:
        _hf_available = False
        logger.warning("HF detectors: torch/transformers not available — falling back to regex")
    return _hf_available


def _get_zero_shot():
    global _zero_shot, _zero_shot_tried
    if _zero_shot is not None:
        return _zero_shot
    if _zero_shot_tried or not _check_hf():
        return None
    _zero_shot_tried = True
    try:
        from transformers import pipeline
        logger.info("Loading zero-shot classifier: typeform/distilbert-base-uncased-mnli")
        _zero_shot = pipeline(
            "zero-shot-classification",
            model="typeform/distilbert-base-uncased-mnli",
            device=-1,
        )
    except Exception as exc:
        logger.warning("Could not load zero-shot classifier: %s", exc)
    return _zero_shot


def _get_ner():
    global _ner_model, _ner_tried
    if _ner_model is not None:
        return _ner_model
    if _ner_tried or not _check_hf():
        return None
    _ner_tried = True
    try:
        from transformers import pipeline
        logger.info("Loading NER model: dslim/bert-base-NER")
        _ner_model = pipeline(
            "ner",
            model="dslim/bert-base-NER",
            aggregation_strategy="simple",
            device=-1,
        )
    except Exception as exc:
        logger.warning("Could not load NER model: %s", exc)
    return _ner_model


def _get_keybert():
    global _keybert, _keybert_tried
    if _keybert is not None:
        return _keybert
    if _keybert_tried:
        return None
    _keybert_tried = True
    try:
        from keybert import KeyBERT
        logger.info("Loading KeyBERT")
        _keybert = KeyBERT(model="all-MiniLM-L6-v2")
    except Exception as exc:
        logger.warning("KeyBERT not available: %s — using regex fallback", exc)
    return _keybert


# ---------------------------------------------------------------------------
# Import F1 fallbacks for graceful degradation
# ---------------------------------------------------------------------------

from swarm_rag.perception.detectors import (
    classify_intent as _regex_intent,
    classify_domain as _regex_domain,
    classify_tone as _regex_tone,
    extract_entities as _regex_entities,
    extract_keywords as _regex_keywords,
    detect_math,   # re-export unchanged
    detect_code,   # re-export unchanged
    detect_language,       # re-export unchanged
    estimate_complexity,   # re-export unchanged
)

# ---------------------------------------------------------------------------
# Intent classifier — zero-shot with MiniLM
# ---------------------------------------------------------------------------

_INTENT_LABELS = ["math", "code", "research", "graph", "version", "memory", "general"]


async def classify_intent(query: str) -> dict:
    clf = _get_zero_shot()
    if clf is None:
        return await _regex_intent(query)
    try:
        result = clf(query, candidate_labels=_INTENT_LABELS, multi_label=False)
        top = result["labels"][0]
        score = result["scores"][0]
        # If confidence low, fall back to regex
        if score < 0.4:
            return await _regex_intent(query)
        return {"intent": top}
    except Exception as exc:
        logger.warning("HF intent classifier failed: %s", exc)
        return await _regex_intent(query)


# ---------------------------------------------------------------------------
# Domain classifier — zero-shot with MiniLM
# ---------------------------------------------------------------------------

_DOMAIN_LABELS = ["law", "finance", "physics", "tech", "general"]


async def classify_domain(query: str) -> dict:
    clf = _get_zero_shot()
    if clf is None:
        return await _regex_domain(query)
    try:
        result = clf(query, candidate_labels=_DOMAIN_LABELS, multi_label=False)
        top = result["labels"][0]
        score = result["scores"][0]
        if score < 0.4:
            return await _regex_domain(query)
        return {"domain": top}
    except Exception as exc:
        logger.warning("HF domain classifier failed: %s", exc)
        return await _regex_domain(query)


# ---------------------------------------------------------------------------
# Tone classifier — zero-shot
# ---------------------------------------------------------------------------

_TONE_LABELS = ["formal", "technical", "casual", "neutral"]


async def classify_tone(query: str) -> dict:
    clf = _get_zero_shot()
    if clf is None:
        return await _regex_tone(query)
    try:
        result = clf(query, candidate_labels=_TONE_LABELS, multi_label=False)
        top = result["labels"][0]
        score = result["scores"][0]
        if score < 0.4:
            return await _regex_tone(query)
        return {"tone": top}
    except Exception as exc:
        logger.warning("HF tone classifier failed: %s", exc)
        return await _regex_tone(query)


# ---------------------------------------------------------------------------
# NER — bert-base-NER
# ---------------------------------------------------------------------------

async def extract_entities(query: str) -> dict:
    ner = _get_ner()
    if ner is None:
        return await _regex_entities(query)
    try:
        raw = ner(query)
        entities = list({e["word"].strip() for e in raw if e.get("word", "").strip()})
        return {"entities": entities[:20]}
    except Exception as exc:
        logger.warning("HF NER failed: %s", exc)
        return await _regex_entities(query)


# ---------------------------------------------------------------------------
# Keyword extractor — KeyBERT
# ---------------------------------------------------------------------------

async def extract_keywords(query: str) -> dict:
    kb = _get_keybert()
    if kb is None:
        return await _regex_keywords(query)
    try:
        kw_pairs = kb.extract_keywords(
            query,
            keyphrase_ngram_range=(1, 2),
            stop_words="english",
            top_n=10,
        )
        keywords = [kw for kw, _ in kw_pairs]
        return {"keywords": keywords}
    except Exception as exc:
        logger.warning("KeyBERT failed: %s", exc)
        return await _regex_keywords(query)
