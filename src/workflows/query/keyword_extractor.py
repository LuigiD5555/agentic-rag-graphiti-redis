"""Lightweight keyword extractor for graph context lookup.

Extracts meaningful terms from a query using simple NLP heuristics —
no external models required.  Used by RAGOrchestrator to build the
keyword list passed to Neo4jRepository.get_related_context().
"""
import re
import unicodedata
from typing import List

# Common stopwords (English + Spanish) to filter out
_STOPWORDS = {
    # English
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "are", "was", "were", "be",
    "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "can", "shall", "what",
    "how", "why", "when", "where", "who", "which", "that", "this", "these",
    "those", "it", "its", "i", "you", "he", "she", "we", "they", "me",
    "him", "her", "us", "them", "my", "your", "his", "our", "their",
    "explain", "describe", "tell", "show", "give", "list", "define",
    "difference", "between", "using", "use", "used", "about",
    # Spanish
    "el", "la", "los", "las", "un", "una", "unos", "unas", "de", "del",
    "al", "en", "con", "por", "para", "que", "qué", "como", "cómo",
    "es", "son", "fue", "ser", "estar", "tiene", "hay", "se", "si",
    "su", "sus", "me", "te", "le", "nos", "les", "mi", "tu", "yo",
    "tú", "él", "ella", "ellos", "ellas", "nosotros", "ustedes",
    "explica", "describe", "dime", "muestra", "define", "qué", "cuál",
    "cuáles", "cuándo", "dónde", "quién", "cuánto",
}

_TOKEN_RE = re.compile(r"[^\w\s]", re.UNICODE)


def _normalize(text: str) -> str:
    """Lowercase and strip accents for comparison."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def extract_keywords(query: str, max_keywords: int = 8) -> List[str]:
    """Extract meaningful keywords from a query string.

    Returns a list of unique, non-trivial tokens suitable for Neo4j
    substring matching.  Preserves original casing of tokens.

    Args:
        query: Raw user query.
        max_keywords: Maximum number of keywords to return.

    Returns:
        List of keyword strings (original casing, deduplicated).
    """
    if not query or not query.strip():
        return []

    # Remove punctuation except hyphens/underscores inside words
    cleaned = _TOKEN_RE.sub(" ", query)

    tokens = cleaned.split()
    seen_normalized: set = set()
    keywords: List[str] = []

    for token in tokens:
        if len(token) < 3:
            continue
        norm = _normalize(token)
        if norm in _STOPWORDS:
            continue
        if norm in seen_normalized:
            continue
        seen_normalized.add(norm)
        keywords.append(token)
        if len(keywords) >= max_keywords:
            break

    return keywords


__all__ = ["extract_keywords"]
