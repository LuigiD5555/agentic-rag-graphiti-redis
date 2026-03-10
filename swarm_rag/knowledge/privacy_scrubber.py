"""
Privacy Scrubber — anonymizes PII before the query leaves the local perimeter.

Two backends (auto-selected):
  1. Microsoft Presidio (if installed: pip install presidio-analyzer presidio-anonymizer)
  2. Regex-based fallback (always available, covers common ES/EN patterns)

Writes to state.perception (anonymized query replaces user_query in-place for
downstream specialists) and stores the entity map for de-anonymization if needed.

Activation: router adds 'privacy_scrubber' when query contains privacy keywords
(confidencial, privado, gdpr, pii, datos personales).

NOTE: The scrubbed query is stored in state.specialists.rewritten_query to avoid
overwriting state.user_query (which is logged/audited). The SLM prompt builder
uses rewritten_query when available.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from swarm_rag.schemas.blackboard_schema import BlackboardState

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Presidio backend (optional)
# ---------------------------------------------------------------------------

_presidio_analyzer = None
_presidio_anonymizer = None
_presidio_tried = False


def _get_presidio():
    global _presidio_analyzer, _presidio_anonymizer, _presidio_tried
    if _presidio_tried:
        return _presidio_analyzer, _presidio_anonymizer
    _presidio_tried = True
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine
        _presidio_analyzer = AnalyzerEngine()
        _presidio_anonymizer = AnonymizerEngine()
        logger.info("PrivacyScrubber: using Microsoft Presidio")
    except ImportError:
        logger.info("PrivacyScrubber: presidio not installed — using regex fallback")
    return _presidio_analyzer, _presidio_anonymizer


# ---------------------------------------------------------------------------
# Regex fallback patterns (ES + EN)
# ---------------------------------------------------------------------------

_REGEX_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Email
    (re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), "<EMAIL>"),
    # Phone (ES format: +34 xxx xxx xxx, or 9-digit)
    (re.compile(r"\+?\d[\d\s\-\(\)]{7,14}\d"), "<PHONE>"),
    # Spanish DNI/NIE
    (re.compile(r"\b\d{8}[A-HJ-NP-TV-Z]\b|\b[XYZ]\d{7}[A-HJ-NP-TV-Z]\b", re.I), "<ID_DOC>"),
    # Credit card (16 digits, possibly grouped)
    (re.compile(r"\b(?:\d{4}[\s\-]?){3}\d{4}\b"), "<CARD>"),
    # IBAN
    (re.compile(r"\b[A-Z]{2}\d{2}[\s]?(?:\d{4}[\s]?){4,6}\b"), "<IBAN>"),
    # Names: "Nombre Apellido" heuristic (two+ capitalized words)
    (re.compile(r"\b([A-ZÁÉÍÓÚ][a-záéíóú]+)\s+([A-ZÁÉÍÓÚ][a-záéíóú]+(?:\s+[A-ZÁÉÍÓÚ][a-záéíóú]+)?)\b"),
     "<PERSONA>"),
]


def _regex_scrub(text: str) -> tuple[str, dict]:
    """Apply regex patterns and return (scrubbed_text, entity_map)."""
    entity_map: dict = {}
    result = text
    for pattern, label in _REGEX_PATTERNS:
        matches = pattern.findall(result)
        for match in matches:
            original = match if isinstance(match, str) else " ".join(match)
            token = f"{label}_{len(entity_map)}"
            entity_map[token] = original
            result = result.replace(original, token, 1)
    return result, entity_map


def _presidio_scrub(text: str, analyzer, anonymizer) -> tuple[str, dict]:
    """Use Presidio to scrub PII."""
    try:
        results = analyzer.analyze(text=text, language="es")
        if not results:
            results = analyzer.analyze(text=text, language="en")
        anonymized = anonymizer.anonymize(text=text, analyzer_results=results)
        entity_map = {
            f"<{r.entity_type}_{i}>": text[r.start:r.end]
            for i, r in enumerate(results)
        }
        return anonymized.text, entity_map
    except Exception as exc:
        logger.warning("Presidio scrub failed: %s — using regex", exc)
        return _regex_scrub(text)


async def run_privacy_scrubber(state: BlackboardState) -> BlackboardState:
    """
    Anonymize PII in the query before it reaches specialists or LLM calls.

    Writes:
        state.specialists.rewritten_query  — anonymized version
        state.retrieval (entity_map stored in execution_trace for audit)
    """
    if "privacy_scrubber" not in state.active_branches:
        return state

    query = state.specialists.rewritten_query or state.user_query
    analyzer, anonymizer = _get_presidio()

    if analyzer and anonymizer:
        scrubbed, entity_map = _presidio_scrub(query, analyzer, anonymizer)
    else:
        scrubbed, entity_map = _regex_scrub(query)

    if entity_map:
        state.specialists.rewritten_query = scrubbed
        # Store map in trace for audit (not in blackboard to avoid leaking PII)
        state.execution_trace.append({
            "layer": "privacy_scrubber",
            "entities_found": len(entity_map),
            "entity_types": list({k.split("_")[0].strip("<>") for k in entity_map}),
        })
        logger.info("PrivacyScrubber: anonymized %d entities", len(entity_map))
    else:
        logger.debug("PrivacyScrubber: no PII detected")

    return state
