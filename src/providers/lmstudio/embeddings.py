"""Module with services that generates embeddings using LM Studio"""
import requests
from src import logger


class EmbeddingService:
    """
    Service to generate embeddings using LM Studio.
    Uses ModelManager to select the first available embedding model.
    """

    def __init__(self, config, model_manager):
        """
        Initialize EmbeddingService with LM Studio endpoint and selected model.
        """
        self.api_root = config.LM_EMBED_URL.rstrip("/")
        if self.api_root.endswith("/v1/embeddings"):
            self.api_root = self.api_root.rsplit("/v1/embeddings", 1)[0]

        self.embed_url = f"{self.api_root}/v1/embeddings"
        self.current_model = model_manager.get_first_embedding_model()

        self.use_dummy = not self.current_model
        if self.use_dummy:
            logger.warning("No embedding model found. Using dummy embeddings.")
        else:
            logger.info("Selected embedding model: %s", self.current_model)

    def generate(self, text: str):
        """
        Generate embedding vector for given text.
        If no model is available, returns dummy vector.
        """
        if self.use_dummy:
            logger.warning("Using dummy embedding vector (768 zeros).")
            return [0.0] * 768

        payload = {"model": self.current_model, "input": text}

        try:
            response = requests.post(self.embed_url, json=payload, timeout=10)
            response.raise_for_status()
            data = response.json()

            embedding = data.get("data", [{}])[0].get("embedding", [0.0] * 768)

            if embedding == [0.0] * 768:
                logger.warning("Received default/fallback embedding for text: %s", text[:50])

            return embedding

        except requests.exceptions.RequestException as e:
            logger.error("Embedding generation failed, using dummy vector: %s", e)
            return [0.0] * 768
