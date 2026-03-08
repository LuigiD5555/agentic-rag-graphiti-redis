"""Contextual Retrieval enrichment — prepends LLM-generated context to each chunk.

Implements the Contextual Retrieval technique (Anthropic, 2024):
  1. For each chunk, ask the LLM to describe what the chunk covers, which
     document/version/section it belongs to, and what concept it addresses.
  2. Prepend that 2-3 sentence prefix to the chunk text before embedding.

The enriched chunk gives the embedding model more signal, improving retrieval
precision especially for version-sensitive or multi-document corpora.

Usage:
    generator = ContextGenerator(chat_service=my_chat_service)
    enriched = generator.enrich_chunk(doc_summary, chunk_text)
"""

import logging
from typing import Optional

from src.workflows.query.interfaces.chat_interface import ChatInterface

log = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """\
Here is a document excerpt:
<document>
{doc_summary}
</document>

Here is a specific chunk from that document:
<chunk>
{chunk_text}
</chunk>

In 2-3 concise sentences, describe:
- Which document, version, or section this chunk belongs to
- What specific concept, topic, or information it covers
- Any key terms or entities that identify this content

Be factual and concise. Do not repeat the chunk verbatim.\
"""


class ContextGenerator:
    """Enriches chunks with LLM-generated context prefix before embedding.

    Args:
        chat_service: Any object implementing ChatInterface (has a .chat() method).
        model: Optional model override for the enrichment call. Defaults to the
               service's default chat model.
        max_tokens: Maximum tokens for the generated context prefix (default: 200).
        doc_chars_limit: How many characters of the document to feed as summary
                         context (default: 3000).
    """

    def __init__(
        self,
        chat_service: ChatInterface,
        model: Optional[str] = None,
        max_tokens: int = 200,
        doc_chars_limit: int = 3000,
    ) -> None:
        self._chat_service = chat_service
        self._model = model or None
        self._max_tokens = max_tokens
        self._doc_chars_limit = doc_chars_limit

    def generate_context(self, doc_summary: str, chunk_text: str) -> str:
        """Return a 2-3 sentence context prefix for the chunk, or '' on failure.

        Args:
            doc_summary: Truncated document text used as context for the LLM.
            chunk_text: The raw chunk text to describe.

        Returns:
            Context prefix string, or empty string if generation fails.
        """
        if not chunk_text or not chunk_text.strip():
            return ""

        # Truncate the doc summary to the configured char limit
        truncated_summary = doc_summary[: self._doc_chars_limit] if doc_summary else ""

        prompt = _PROMPT_TEMPLATE.format(
            doc_summary=truncated_summary,
            chunk_text=chunk_text,
        )

        messages = [{"role": "user", "content": prompt}]

        try:
            result = self._chat_service.chat(
                messages=messages,
                max_tokens=self._max_tokens,
                model=self._model,
            )
            prefix = (result or "").strip()
            if not prefix:
                log.debug("ContextGenerator: empty response from LLM, skipping enrichment")
                return ""
            return prefix
        except Exception as exc:
            log.warning("ContextGenerator: LLM call failed, skipping enrichment: %s", exc)
            return ""

    def enrich_chunk(self, doc_summary: str, chunk_text: str) -> str:
        """Return context_prefix + '\\n\\n' + chunk_text, or chunk_text unchanged on failure.

        Args:
            doc_summary: Document text used as context for the LLM.
            chunk_text: The raw chunk text to enrich.

        Returns:
            Enriched chunk text, or the original chunk_text if enrichment fails.
        """
        prefix = self.generate_context(doc_summary, chunk_text)
        if not prefix:
            return chunk_text
        return f"{prefix}\n\n{chunk_text}"
