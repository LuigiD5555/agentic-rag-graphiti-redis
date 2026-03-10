"""
F1 Perception detectors — regex + heuristic implementations.

Each detector is an async function:
  async def run(query: str) -> dict

These are the F1 provisional implementations. In F2, each function will be
replaced by a HuggingFace model (MiniLM, bert-base-NER, etc.) with the
SAME signature — the perception_layer.py orchestrator doesn't change.

Loaded once at module import. No per-query overhead beyond the computation.
"""
from __future__ import annotations

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Language detector — langdetect (already installed)
# ---------------------------------------------------------------------------

try:
    from langdetect import detect as _langdetect
    _LANGDETECT_OK = True
except ImportError:
    _LANGDETECT_OK = False
    logger.warning("langdetect not available — defaulting to 'es'")


async def detect_language(query: str) -> dict:
    if not _LANGDETECT_OK or len(query.strip()) < 5:
        return {"language": "es"}
    try:
        lang = _langdetect(query)
        return {"language": lang}
    except Exception:
        return {"language": "es"}


# ---------------------------------------------------------------------------
# Math detector — regex patterns
# ---------------------------------------------------------------------------

_MATH_KEYWORDS = re.compile(
    r"\b(calcula|calculo|calci|porcentaje|porciento|suma|resta|divide|multiplica"
    r"|integral|derivada|ecuacion|ecuación|formula|fórmula|resultado|cuanto es|cuánto"
    r"|calculate|percent|equation|compute|average|promedio|media|varianza|desviacion"
    r"|factorial|raiz|sqrt|logaritmo|log|exponente)\b",
    re.IGNORECASE,
)
_MATH_SYMBOLS = re.compile(r"[+\-*/=÷×√∑∫∂π%]|\d+\s*[+\-*/]\s*\d+|\d+%")


async def detect_math(query: str) -> dict:
    has_kw = bool(_MATH_KEYWORDS.search(query))
    has_sym = bool(_MATH_SYMBOLS.search(query))
    return {"needs_math": has_kw or has_sym}


# ---------------------------------------------------------------------------
# Code detector — regex patterns
# ---------------------------------------------------------------------------

_CODE_KEYWORDS = re.compile(
    r"\b(python|javascript|typescript|java|golang|rust|c\+\+|kotlin|ruby"
    r"|funcion|función|metodo|método|clase|modulo|módulo|bug|error|traceback"
    r"|import|def |class |function|codigo|código|script|implementa|refactor"
    r"|compile|syntax|exception|excepción|stacktrace|debugg?)\b",
    re.IGNORECASE,
)
_CODE_BLOCK = re.compile(r"```|`[^`]+`|def\s+\w+\(|class\s+\w+[\(:]")


async def detect_code(query: str) -> dict:
    has_kw = bool(_CODE_KEYWORDS.search(query))
    has_block = bool(_CODE_BLOCK.search(query))
    return {"needs_code": has_kw or has_block}


# ---------------------------------------------------------------------------
# Intent classifier — rule-based (F1), HF MiniLM in F2
# ---------------------------------------------------------------------------

_INTENT_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(calcula|porcentaje|suma|divide|ecuacion|formula|result)\b", re.I), "math"),
    (re.compile(r"\b(bug|error|debug|codigo|clase|funcion|metodo|python|javascript|java)\b", re.I), "code"),
    (re.compile(r"\b(relacion|conecta|depende|grafo|neo4j|entidad|nodo)\b", re.I), "graph"),
    (re.compile(r"\b(version|vigente|obsoleto|anterior|cambio|2023|2024|2025|2026)\b", re.I), "version"),
    (re.compile(r"\b(recuerdas|anteriormente|antes|previo|solucionamos)\b", re.I), "memory"),
    (re.compile(r"\b(busca|encuentra|que dice|qué dice|muestra|explica|describe|resume|resumen)\b", re.I), "research"),
]


async def classify_intent(query: str) -> dict:
    for pattern, intent in _INTENT_RULES:
        if pattern.search(query):
            return {"intent": intent}
    return {"intent": "general"}


# ---------------------------------------------------------------------------
# Domain classifier — zero-shot heuristic (F1), MiniLM in F2
# ---------------------------------------------------------------------------

_DOMAIN_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(contrato|penalizacion|clausula|legal|ley|articulo|vigente|juridico)\b", re.I), "law"),
    (re.compile(r"\b(precio|costo|costo|revenue|ganancia|perdida|financiero|impuesto|iva|tasa)\b", re.I), "finance"),
    (re.compile(r"\b(fuerza|masa|energia|velocidad|aceleracion|gravedad|fisica|quimica|molecula)\b", re.I), "physics"),
    (re.compile(r"\b(python|codigo|algoritmo|software|api|base de datos|sistema)\b", re.I), "tech"),
]


async def classify_domain(query: str) -> dict:
    for pattern, domain in _DOMAIN_RULES:
        if pattern.search(query):
            return {"domain": domain}
    return {"domain": "general"}


# ---------------------------------------------------------------------------
# Complexity estimator — heuristic (F1), DistilBERT in F2
# ---------------------------------------------------------------------------

_COMPLEX_PATTERNS = re.compile(
    r"\b(compara|analiza|explica|relaciona|vs\.|versus|multi|combinado|ademas|tambien"
    r"|compare|analyze|explain|relationship|furthermore)\b",
    re.IGNORECASE,
)


async def estimate_complexity(query: str) -> dict:
    words = len(query.split())
    has_complex = bool(_COMPLEX_PATTERNS.search(query))
    question_marks = query.count("?")

    if words > 30 or (has_complex and words > 15) or question_marks > 1:
        complexity = "high"
    elif words > 12 or has_complex:
        complexity = "medium"
    else:
        complexity = "low"
    return {"complexity": complexity}


# ---------------------------------------------------------------------------
# NER — simple regex (F1), bert-base-NER in F2
# ---------------------------------------------------------------------------

_ENTITY_PATTERNS = [
    re.compile(r"\b(contrato|Contract)\s*\d{4}\b", re.I),
    re.compile(r"\b(artículo|articulo|art\.?)\s*\d+\b", re.I),
    re.compile(r"\b20\d{2}\b"),                            # years
    re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+\b"),    # proper nouns (capitalized phrases)
]


async def extract_entities(query: str) -> dict:
    found: list[str] = []
    for pattern in _ENTITY_PATTERNS:
        found.extend(m.group(0) for m in pattern.finditer(query))
    # Deduplicate preserving order
    seen: set[str] = set()
    entities = [e for e in found if not (e in seen or seen.add(e))]  # type: ignore[func-returns-value]
    return {"entities": entities}


# ---------------------------------------------------------------------------
# Keyword extractor — simple NLTK stopword removal (F1), KeyBERT in F2
# ---------------------------------------------------------------------------

_STOPWORDS_ES = {
    "el", "la", "los", "las", "un", "una", "de", "del", "en", "con", "por",
    "para", "que", "qué", "es", "son", "hay", "se", "me", "te", "nos", "su",
    "sus", "al", "lo", "si", "más", "como", "entre", "sobre", "desde", "hasta",
    "y", "o", "a", "e", "u", "ni"
}
_STOPWORDS_EN = {
    "the", "is", "are", "of", "in", "and", "or", "a", "an", "to", "for",
    "it", "its", "that", "this", "with", "by", "from", "as", "at", "be"
}
_ALL_STOPS = _STOPWORDS_ES | _STOPWORDS_EN


async def extract_keywords(query: str) -> dict:
    tokens = re.findall(r"[a-záéíóúüñA-Z]{4,}", query)
    kw = [t.lower() for t in tokens if t.lower() not in _ALL_STOPS]
    seen: set[str] = set()
    unique = [k for k in kw if not (k in seen or seen.add(k))]  # type: ignore[func-returns-value]
    return {"keywords": unique[:10]}


# ---------------------------------------------------------------------------
# Tone classifier — heuristic (F1), MiniLM in F2
# ---------------------------------------------------------------------------

_FORMAL_PATTERNS = re.compile(
    r"\b(estimado|cordialmente|atentamente|según|conforme|mediante|el presente|dicho)\b",
    re.I,
)
_TECHNICAL_PATTERNS = re.compile(
    r"\b(implementa|algoritmo|función|clase|método|api|endpoint|query|schema|pipeline)\b",
    re.I,
)
_CASUAL_PATTERNS = re.compile(
    r"\b(hola|oye|hey|bueno|genial|ok|gracias|claro|dale|porfa)\b",
    re.I,
)


async def classify_tone(query: str) -> dict:
    if _FORMAL_PATTERNS.search(query):
        return {"tone": "formal"}
    if _TECHNICAL_PATTERNS.search(query):
        return {"tone": "technical"}
    if _CASUAL_PATTERNS.search(query):
        return {"tone": "casual"}
    return {"tone": "neutral"}
