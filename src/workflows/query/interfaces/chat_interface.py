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
        request_id: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> str:
        """Send chat completion request with message history."""
        ...

    def complete(
        self,
        prompt: str,
        max_tokens: int = 256,
        request_id: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> str:
        """Simple completion (single user message)."""
        ...
