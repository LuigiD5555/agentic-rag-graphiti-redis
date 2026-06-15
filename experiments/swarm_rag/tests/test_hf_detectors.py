"""
Tests for hf_detectors.py — HuggingFace perception backend.

All HF models are mocked. Tests verify:
- When HF is available: model output is used (if confidence >= threshold)
- When HF confidence is low: fallback to regex result
- When HF unavailable (import error): falls back to regex silently
- Each detector has identical output schema as F1 regex detectors
"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

import experiments.swarm_rag.perception.hf_detectors as hf
from pytest_readable import readable



def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _mock_zero_shot(labels, scores):
    """Return a mock zero-shot classifier result."""
    mock = MagicMock()
    mock.return_value = {"labels": labels, "scores": scores}
    return mock


# ---------------------------------------------------------------------------
# Intent classifier
# ---------------------------------------------------------------------------

class TestHFIntent:
    @readable(
        intent="Verify uses top label when confident in h f intent.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the uses top label when confident behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_uses_top_label_when_confident(self):
        with patch.object(hf, "_zero_shot", _mock_zero_shot(["math", "general"], [0.9, 0.1])):
            result = _run(hf.classify_intent("calcula el IVA"))
        assert result["intent"] == "math"

    @readable(
        intent="Verify falls back to regex when low confidence in h f intent.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the falls back to regex when low confidence behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_falls_back_to_regex_when_low_confidence(self):
        with patch.object(hf, "_zero_shot", _mock_zero_shot(["math", "general"], [0.2, 0.1])):
            # Low confidence — should use regex. "calcula" → math via regex
            result = _run(hf.classify_intent("calcula el IVA"))
        assert result["intent"] == "math"  # regex also catches it

    @readable(
        intent="Verify falls back when no model in h f intent.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the falls back when no model behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_falls_back_when_no_model(self):
        with patch.object(hf, "_zero_shot", None):
            with patch.object(hf, "_zero_shot_tried", True):
                result = _run(hf.classify_intent("hay un bug en Python"))
        assert result["intent"] == "code"  # regex fallback

    @readable(
        intent="Verify returns dict with intent key in h f intent.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the returns dict with intent key behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_returns_dict_with_intent_key(self):
        with patch.object(hf, "_zero_shot", _mock_zero_shot(["research"], [0.8])):
            result = _run(hf.classify_intent("explica el contrato"))
        assert "intent" in result

    @readable(
        intent="Verify handles model exception in h f intent.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the handles model exception behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_handles_model_exception(self):
        bad_mock = MagicMock(side_effect=RuntimeError("model crashed"))
        with patch.object(hf, "_zero_shot", bad_mock):
            result = _run(hf.classify_intent("calcula el total"))
        assert "intent" in result  # regex fallback still works


# ---------------------------------------------------------------------------
# Domain classifier
# ---------------------------------------------------------------------------

class TestHFDomain:
    @readable(
        intent="Verify uses top label when confident in h f domain.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the uses top label when confident behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_uses_top_label_when_confident(self):
        with patch.object(hf, "_zero_shot", _mock_zero_shot(["law", "finance"], [0.85, 0.1])):
            result = _run(hf.classify_domain("el contrato vigente establece"))
        assert result["domain"] == "law"

    @readable(
        intent="Verify falls back on low confidence in h f domain.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the falls back on low confidence behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_falls_back_on_low_confidence(self):
        with patch.object(hf, "_zero_shot", _mock_zero_shot(["law", "general"], [0.3, 0.2])):
            result = _run(hf.classify_domain("el contrato vigente establece"))
        assert result["domain"] == "law"  # regex also detects "contrato"

    @readable(
        intent="Verify returns dict with domain key in h f domain.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the returns dict with domain key behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_returns_dict_with_domain_key(self):
        with patch.object(hf, "_zero_shot", _mock_zero_shot(["tech"], [0.7])):
            result = _run(hf.classify_domain("el algoritmo"))
        assert "domain" in result


# ---------------------------------------------------------------------------
# Tone classifier
# ---------------------------------------------------------------------------

class TestHFTone:
    @readable(
        intent="Verify uses hf tone in h f tone.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the uses hf tone behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_uses_hf_tone(self):
        with patch.object(hf, "_zero_shot", _mock_zero_shot(["formal", "neutral"], [0.75, 0.2])):
            result = _run(hf.classify_tone("según el presente contrato"))
        assert result["tone"] == "formal"

    @readable(
        intent="Verify returns dict with tone key in h f tone.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the returns dict with tone key behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_returns_dict_with_tone_key(self):
        with patch.object(hf, "_zero_shot", _mock_zero_shot(["technical"], [0.6])):
            result = _run(hf.classify_tone("la API devuelve un JSON"))
        assert "tone" in result


# ---------------------------------------------------------------------------
# NER
# ---------------------------------------------------------------------------

class TestHFNER:
    @readable(
        intent="Verify extracts entities from ner output in h f n e r.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the extracts entities from ner output behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_extracts_entities_from_ner_output(self):
        ner_mock = MagicMock(return_value=[
            {"word": "Artículo 5", "entity_group": "MISC", "score": 0.95},
            {"word": "2024", "entity_group": "DATE", "score": 0.90},
        ])
        with patch.object(hf, "_ner_model", ner_mock):
            result = _run(hf.extract_entities("el Artículo 5 del contrato de 2024"))
        assert "entities" in result
        assert "Artículo 5" in result["entities"]
        assert "2024" in result["entities"]

    @readable(
        intent="Verify deduplicates entities in h f n e r.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the deduplicates entities behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_deduplicates_entities(self):
        ner_mock = MagicMock(return_value=[
            {"word": "contrato", "entity_group": "MISC", "score": 0.9},
            {"word": "contrato", "entity_group": "MISC", "score": 0.85},
        ])
        with patch.object(hf, "_ner_model", ner_mock):
            result = _run(hf.extract_entities("el contrato y el contrato"))
        assert result["entities"].count("contrato") == 1

    @readable(
        intent="Verify falls back when no model in h f n e r.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the falls back when no model behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_falls_back_when_no_model(self):
        with patch.object(hf, "_ner_model", None):
            with patch.object(hf, "_ner_tried", True):
                result = _run(hf.extract_entities("Artículo 5 del año 2024"))
        assert "entities" in result

    @readable(
        intent="Verify handles model exception in h f n e r.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the handles model exception behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_handles_model_exception(self):
        ner_mock = MagicMock(side_effect=RuntimeError("NER failed"))
        with patch.object(hf, "_ner_model", ner_mock):
            result = _run(hf.extract_entities("Artículo 5"))
        assert "entities" in result


# ---------------------------------------------------------------------------
# KeyBERT keywords
# ---------------------------------------------------------------------------

class TestHFKeywords:
    @readable(
        intent="Verify extracts keyphrases in h f keywords.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the extracts keyphrases behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_extracts_keyphrases(self):
        kb_mock = MagicMock()
        kb_mock.extract_keywords.return_value = [
            ("contract penalty", 0.85),
            ("penalty clause", 0.72),
        ]
        with patch.object(hf, "_keybert", kb_mock):
            result = _run(hf.extract_keywords("the contract penalty clause applies"))
        assert "keywords" in result
        assert "contract penalty" in result["keywords"]

    @readable(
        intent="Verify falls back when no keybert in h f keywords.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the falls back when no keybert behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_falls_back_when_no_keybert(self):
        with patch.object(hf, "_keybert", None):
            with patch.object(hf, "_hf_available", True):
                result = _run(hf.extract_keywords("contrato vigente penalización anual"))
        assert "keywords" in result
        assert "contrato" in result["keywords"]

    @readable(
        intent="Verify returns list in h f keywords.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the returns list behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_returns_list(self):
        kb_mock = MagicMock()
        kb_mock.extract_keywords.return_value = [("penalty", 0.9)]
        with patch.object(hf, "_keybert", kb_mock):
            result = _run(hf.extract_keywords("penalty"))
        assert isinstance(result["keywords"], list)


# ---------------------------------------------------------------------------
# Re-exported detectors (same as F1 — verify they pass through)
# ---------------------------------------------------------------------------

class TestReExportedDetectors:
    @readable(
        intent="Verify detect math still works in re exported detectors.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the detect math still works behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_detect_math_still_works(self):
        result = _run(hf.detect_math("calcula el 15%"))
        assert result["needs_math"] is True

    @readable(
        intent="Verify detect code still works in re exported detectors.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the detect code still works behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_detect_code_still_works(self):
        result = _run(hf.detect_code("hay un bug en Python"))
        assert result["needs_code"] is True

    @readable(
        intent="Verify detect language still works in re exported detectors.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the detect language still works behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_detect_language_still_works(self):
        result = _run(hf.detect_language("hello world this is english"))
        assert "language" in result

    @readable(
        intent="Verify estimate complexity still works in re exported detectors.",
        steps=[
            "Set up the inputs and collaborators for the scenario.",
            "Run the estimate complexity still works behavior under test.",
            "Check the observable result and assertions.",
        ],
        criteria=[
            "The assertions confirm the documented behavior.",
        ],
    )
    def test_estimate_complexity_still_works(self):
        result = _run(hf.estimate_complexity("¿qué?"))
        assert result["complexity"] in ("low", "medium", "high")
