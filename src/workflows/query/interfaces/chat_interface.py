from typing import Protocol, List, Dict, Optional


class ChatInterface(Protocol):
    """
    Interface for chat/completion backends.
    """
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
    ) -> str:
        """Send chat completion request with message history."""
        ...

    def complete(self, prompt: str, max_tokens: int = 256) -> str:
        """Simple completion (single user message)."""
        ...
