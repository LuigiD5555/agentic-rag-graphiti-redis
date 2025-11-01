"""Module with services that communicate RAG requests to LM Studio API."""
import requests
from src import logger


class LLMService:
    """
    Service to get completions from LM Studio using OpenAI-compatible API.
    Uses ModelManager to select the first available non-embedding model.
    """

    def __init__(self, config, model_manager, temperature: float = 0.7):
        """
        Initialize LLMService with LM Studio endpoint and selected model.
        """
        host = config.LMSTUDIO_HOST
        port = config.LMSTUDIO_PORT
        self.api_root = f"http://{host}:{port}"
        self.url = f"{self.api_root}/v1/chat/completions"

        self.model = model_manager.get_first_language_model() or "gpt-3.5-turbo"
        self.temperature = temperature

        logger.info("Selected LLM model: %s", self.model)

    def complete(self, prompt: str, max_tokens: int = 256) -> str:
        """
        Request chat completion from LM Studio using the selected LLM model.
        """
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": prompt}
            ],
            "temperature": self.temperature,
            "max_tokens": max_tokens
        }

        try:
            logger.info("Sending chat completion request to LM Studio (model=%s, max_tokens=%d)...",
                        self.model, max_tokens)
            response = requests.post(self.url, json=payload, timeout=30)
            response.raise_for_status()

            data = response.json()
            text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()

            if not text:
                logger.warning("LM Studio returned an empty chat completion response.")
            else:
                logger.info("Received chat completion response (%d chars).", len(text))

            return text

        except requests.exceptions.RequestException as e:
            logger.error("Failed to connect to LM Studio for chat completion: %s", e)
            return ""
