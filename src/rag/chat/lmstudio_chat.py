"""LM Studio chat service for RAG generation."""
from typing import List, Dict, Optional
from openai import OpenAI
from src.rag.audit import get_logger
from src.rag.models import is_embedding_model

log = get_logger(__name__)


def _normalize_model_name(model_name: str) -> str:
    """Remove Ollama-style version tags from model name.

    Open WebUI sends models like 'liquid/lfm2-1.2b:latest' but LM Studio
    expects just 'liquid/lfm2-1.2b'. This function strips the tag.

    Args:
        model_name: Model name possibly with tag (e.g., 'model:latest', 'model:v1')

    Returns:
        Model name without tag
    """
    if ':' in model_name:
        return model_name.split(':', 1)[0]
    return model_name


class LMStudioChatService:
    """Chat service using LM Studio's OpenAI-compatible API."""

    def __init__(
        self,
        base_url: str,
        api_key: str = "lm-studio",
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        keep_alive: Optional[int] = None,
    ):
        """Initialize LM Studio chat service.

        Args:
            base_url: LM Studio API base URL (e.g., "http://localhost:1234/v1").
            api_key: API key (LM Studio doesn't require real key, use placeholder).
            model: Specific model to use, or None to use first available.
            temperature: Sampling temperature (0.0-1.0).
            max_tokens: Maximum tokens in response.
            keep_alive: Seconds to keep model loaded (0=unload immediately, None=server default).
        """
        log.info("Creating OpenAI client with base_url=%s", base_url)
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.keep_alive = keep_alive

        # Auto-detect model if not specified
        if not self.model:
            self.model = self._get_first_available_model()

        log.info(
            "Initialized LMStudioChatService: model=%s, temp=%.2f, max_tokens=%d, keep_alive=%s",
            self.model, temperature, max_tokens, keep_alive
        )

    def _get_first_available_model(self) -> str:
        """Get first available non-embedding model from LM Studio."""
        try:
            models = self.client.models.list()
            if models.data:
                # Filter out embedding models and select first language model
                for model in models.data:
                    model_id = model.id
                    if not is_embedding_model(model_id):
                        log.info("Auto-selected language model: %s", model_id)
                        return model_id

                # Fallback: if all models are embedding models, use first anyway
                model_id = models.data[0].id
                log.warning("No language models found, using first model: %s", model_id)
                return model_id
            else:
                log.warning("No models found in LM Studio, using fallback")
                return "default"
        except Exception as e:
            log.error("Failed to list models: %s. Using 'default'", e)
            return "default"

    def _ensure_model_loaded(self, model_name: str) -> bool:
        """Ensure model is loaded in LM Studio.

        LM Studio loads models on-demand when they're first used. This method
        sends a minimal test request to warm up the model and verify it can load.

        Args:
            model_name: Name of the model to load

        Returns:
            True if model loaded successfully, False otherwise
        """
        try:
            log.info("Checking if model %s is loaded...", model_name)
            # Send a minimal warmup request to load the model
            # Use keep_alive=0 to unload immediately after test
            response = self.client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": "test"}],
                max_tokens=1,  # Minimal tokens to speed up warmup
                temperature=0.1,
                extra_body={"keep_alive": 0},  # Unload immediately after test
            )

            if response and response.choices:
                log.info("Model %s loaded successfully", model_name)
                return True
            else:
                log.warning("Model %s warmup returned empty response", model_name)
                return False

        except Exception as e:
            error_str = str(e)
            if "Failed to load model" in error_str or "Operation canceled" in error_str:
                log.error("Model %s failed to load: %s", model_name, error_str)
                return False
            else:
                # Other errors might be transient
                log.warning("Model %s warmup error (might still work): %s", model_name, error_str)
                return True  # Try to proceed anyway

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
    ) -> str:
        """Send chat completion request.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            temperature: Override default temperature.
            max_tokens: Override default max_tokens.
            model: Override default model (allows per-request model selection).

        Returns:
            Generated response text.
        """
        temp = temperature if temperature is not None else self.temperature
        tokens = max_tokens if max_tokens is not None else self.max_tokens
        selected_model = model if model is not None else self.model

        # Normalize model name: remove Ollama-style tags like ':latest'
        # Open WebUI sends 'liquid/lfm2-1.2b:latest' but LM Studio expects 'liquid/lfm2-1.2b'
        if selected_model:
            normalized_model = _normalize_model_name(selected_model)
        else:
            log.error("No model specified and no default model available")
            return "Error: No model specified"

        try:
            # Ensure model is loaded before making the actual request
            if not self._ensure_model_loaded(normalized_model):
                error_msg = f"Model {normalized_model} is not available or failed to load in LM Studio. Please load the model manually in LM Studio first."
                log.error(error_msg)
                return f"Error: {error_msg}"

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
                "Sending chat request: model=%s (normalized to %s), %d messages, temp=%.2f, max_tokens=%d",
                selected_model, normalized_model, len(cleaned_messages), temp, tokens
            )
            log.info("Messages to send: %s", cleaned_messages)

            log.info("Calling LM Studio with model=%s, keep_alive=%s", normalized_model, self.keep_alive)

            # Build request parameters
            request_params = {
                "model": normalized_model,
                "messages": cleaned_messages,
                "temperature": temp,
                "max_tokens": tokens,
            }

            # Add keep_alive if specified (LM Studio extension)
            if self.keep_alive is not None:
                request_params["extra_body"] = {"keep_alive": self.keep_alive}

            response = self.client.chat.completions.create(**request_params)
            log.info("Received response type: %s, has choices: %s, choices length: %s",
                    type(response),
                    hasattr(response, 'choices'),
                    len(response.choices) if hasattr(response, 'choices') and response.choices else 0)

            if not response or not response.choices:
                log.error("Empty response from LM Studio for model %s", normalized_model)
                return f"Error: No response from LM Studio for model {normalized_model}"

            content = response.choices[0].message.content
            if content is None:
                log.error("Response content is None for model %s", normalized_model)
                return f"Error: Empty content from model {normalized_model}"

            log.info("Generated response with model %s: %d chars", normalized_model, len(content))
            return content

        except UnicodeEncodeError as e:
            error_msg = f"Encoding error: Could not process the text. Please use only valid UTF-8 characters."
            log.error("Chat completion encoding failed: %s", e)
            return error_msg
        except Exception as e:
            error_msg = "Could not generate response. " + str(e)
            log.error("Chat completion failed with model %s: %s", selected_model, e, exc_info=True)
            return "Error: " + error_msg

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
