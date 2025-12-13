from typing import Protocol


class ChatInterface(Protocol):
    """
    Interface for chat/completion backends.
    """
    def complete(self, prompt: str, max_tokens: int = 256) -> str:
        ...
