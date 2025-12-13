"""HuggingFaceChat for handling chat completions."""
from src.rag.interfaces.chat_interface import ChatInterface


class HuggingFaceChat(ChatInterface):
    """
    HuggingFaceChat implementation for handling chat completions.
    """
    def complete(self, prompt: str, max_tokens: int = 256) -> str:
        raise NotImplementedError
