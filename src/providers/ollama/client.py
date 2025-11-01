"""
OllamaChat for handling chat completions.
"""

from src.interfaces.chat_interface import ChatInterface


class OllamaChat(ChatInterface):
    """
    OllamaChat implementation for handling chat completions.
    """
    def complete(self, prompt: str, max_tokens: int = 256) -> str:
        raise NotImplementedError
