"""AnychintLLMChat for interacting with the Anything LLM API."""
from src.interfaces.chat_interface import ChatInterface


class AnythingLLMChat(ChatInterface):
    """AnythingLLMChat implementation for handling chat completion with Anything LLM API."""
    def complete(self, prompt: str, max_tokens: int = 256) -> str:
        raise NotImplementedError
