"""LM Studio chat service for RAG generation."""
from typing import List, Dict, Optional
from openai import OpenAI
from src.rag.audit import get_logger

log = get_logger(__name__)


class LMStudioChatService:
    """Chat service using LM Studio's OpenAI-compatible API."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "lm-studio",
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ):
        """Initialize LM Studio chat service.

        Args:
            base_url: LM Studio API base URL (e.g., "http://localhost:1234/v1").
            api_key: API key (LM Studio doesn't require real key, use placeholder).
            model: Specific model to use, or None to use first available.
            temperature: Sampling temperature (0.0-1.0).
            max_tokens: Maximum tokens in response.
        """
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

        # Auto-detect model if not specified
        if not self.model:
            self.model = self._get_first_available_model()

        log.info(
            "Initialized LMStudioChatService: model=%s, temp=%.2f, max_tokens=%d",
            self.model, temperature, max_tokens
        )

    def _get_first_available_model(self) -> str:
        """Get first available model from LM Studio."""
        try:
            models = self.client.models.list()
            if models.data:
                model_id = models.data[0].id
                log.info("Auto-selected model: %s", model_id)
                return model_id
            else:
                log.warning("No models found in LM Studio, using fallback")
                return "default"
        except Exception as e:
            log.error("Failed to list models: %s. Using 'default'", e)
            return "default"

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Send chat completion request.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            temperature: Override default temperature.
            max_tokens: Override default max_tokens.

        Returns:
            Generated response text.
        """
        temp = temperature if temperature is not None else self.temperature
        tokens = max_tokens if max_tokens is not None else self.max_tokens

        try:
            # Clean messages from potential encoding issues
            cleaned_messages = []
            for msg in messages:
                cleaned_msg = msg.copy()
                if 'content' in cleaned_msg:
                    # Handle surrogate characters and encoding issues
                    content = cleaned_msg['content']
                    if isinstance(content, str):
                        content = content.encode('utf-8', errors='surrogatepass').decode('utf-8', errors='ignore')
                        cleaned_msg['content'] = content
                cleaned_messages.append(cleaned_msg)

            log.debug(
                "Sending chat request: %d messages, temp=%.2f, max_tokens=%d",
                len(cleaned_messages), temp, tokens
            )

            response = self.client.chat.completions.create(
                model=self.model,
                messages=cleaned_messages,
                temperature=temp,
                max_tokens=tokens,
            )

            content = response.choices[0].message.content
            log.info("Generated response: %d chars", len(content))
            return content

        except UnicodeEncodeError as e:
            error_msg = f"Encoding error: Could not process the text. Please use only valid UTF-8 characters."
            log.error("Chat completion encoding failed: %s", e)
            return error_msg
        except Exception as e:
            error_msg = f"Could not generate response. {str(e)}"
            log.error("Chat completion failed: %s", e)
            return f"Error: {error_msg}"

    def complete(
        self,
        prompt: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Simple completion (single user message).

        Args:
            prompt: User prompt/question.
            temperature: Sampling temperature.
            max_tokens: Max response tokens.

        Returns:
            Generated completion.
        """
        messages = [{"role": "user", "content": prompt}]
        return self.chat(messages, temperature=temperature, max_tokens=max_tokens)


__all__ = ["LMStudioChatService"]
