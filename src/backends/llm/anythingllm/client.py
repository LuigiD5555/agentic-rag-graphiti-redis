"""AnychintLLMChat for interacting with the Anything LLM API."""
from typing import Dict, List, Optional

from src.workflows.query.interfaces.chat_interface import ChatInterface


class AnythingLLMChat(ChatInterface):
    """AnythingLLMChat implementation for handling chat completion with Anything LLM API."""

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        request_id: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> str:
        raise NotImplementedError

    def complete(
        self,
        prompt: str,
        max_tokens: int = 256,
        request_id: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> str:
        raise NotImplementedError
