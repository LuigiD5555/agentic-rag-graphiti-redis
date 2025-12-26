"""LLM-based summarizer using LFM2-1.2B for memory compression."""
import logging
import os
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class LLMSummarizer:
    """LLM-based summarizer for conversation compression.

    Uses LFM2-1.2B (or configured model) to intelligently summarize
    conversations while preserving key information.
    """

    COMPRESSION_PROMPT = """Resume la siguiente conversación manteniendo SOLO:
- Decisiones tomadas
- Intenciones del usuario
- Estado actual de la tarea
- Referencias a documentos/herramientas usados

Descarta:
- Saludos y despedidas
- Confirmaciones simples ("ok", "sí", "entiendo")
- Texto decorativo o redundante
- Información ya ejecutada sin relevancia futura

Responde con un resumen conciso de máximo 3-4 oraciones.

Conversación:
{conversation}

Resumen:"""

    def __init__(
        self,
        model_endpoint: Optional[str] = None,
        model_name: Optional[str] = None,
        max_tokens: int = 500
    ):
        """Initialize LLM summarizer.

        Args:
            model_endpoint: LM Studio endpoint (defaults to env var)
            model_name: Model name (defaults to env var or "lfm2-1.2b")
            max_tokens: Max tokens for summary
        """
        self.endpoint = model_endpoint or os.getenv(
            "COMPRESSION_MODEL_ENDPOINT",
            "http://127.0.0.1:1234/v1/chat/completions"
        )
        self.model_name = model_name or os.getenv(
            "COMPRESSION_MODEL_NAME",
            "lfm2-1.2b"
        )
        self.max_tokens = max_tokens

        logger.info(
            f"LLMSummarizer initialized: endpoint={self.endpoint}, "
            f"model={self.model_name}"
        )

    def summarize(
        self,
        conversation: str,
        max_tokens: Optional[int] = None
    ) -> str:
        """Summarize conversation using LLM.

        Args:
            conversation: Conversation text to summarize
            max_tokens: Override max tokens (optional)

        Returns:
            Compressed summary string

        Raises:
            Exception: If LLM call fails
        """
        if not conversation.strip():
            return ""

        max_tokens = max_tokens or self.max_tokens

        # Build prompt
        prompt = self.COMPRESSION_PROMPT.format(conversation=conversation)

        # Call LM Studio API (OpenAI-compatible)
        try:
            response = requests.post(
                self.endpoint,
                json={
                    "model": self.model_name,
                    "messages": [
                        {"role": "user", "content": prompt}
                    ],
                    "max_tokens": max_tokens,
                    "temperature": 0.3,  # Low temp for consistent summaries
                    "stream": False
                },
                timeout=30
            )

            response.raise_for_status()
            result = response.json()

            summary = result["choices"][0]["message"]["content"].strip()

            logger.info(
                f"LLM summarization: {len(conversation)} chars -> "
                f"{len(summary)} chars "
                f"({len(summary)/len(conversation)*100:.1f}%)"
            )

            return summary

        except requests.exceptions.RequestException as e:
            logger.error(f"LLM summarization failed: {e}")
            # Fallback: return truncated original
            fallback = conversation[:max_tokens * 4]
            if len(conversation) > len(fallback):
                fallback += "..."
            logger.warning(f"Using fallback truncation instead")
            return fallback

    def summarize_messages(
        self,
        messages: list[dict],
        max_tokens: Optional[int] = None
    ) -> str:
        """Summarize list of messages.

        Args:
            messages: List of message dicts with 'role' and 'content'
            max_tokens: Override max tokens (optional)

        Returns:
            Compressed summary string
        """
        if not messages:
            return ""

        # Format messages as conversation
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            lines.append(f"{role}: {content}")

        conversation = "\n".join(lines)

        return self.summarize(conversation, max_tokens)


def create_summarizer(
    endpoint: Optional[str] = None,
    model_name: Optional[str] = None
) -> LLMSummarizer:
    """Factory function to create LLM summarizer.

    Args:
        endpoint: Optional endpoint override
        model_name: Optional model name override

    Returns:
        Configured LLMSummarizer instance
    """
    return LLMSummarizer(
        model_endpoint=endpoint,
        model_name=model_name
    )