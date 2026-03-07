"""
OllamaChat for handling chat completions.
"""

from typing import Dict, List, Optional

from src.workflows.query.interfaces.chat_interface import ChatInterface


class OllamaChat(ChatInterface):
    """
    OllamaChat implementation for handling chat completions.
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
        raise NotImplementedError

    def complete(
        self,
        prompt: str,
        max_tokens: int = 256,
        request_id: Optional[str] = None,
        ttl: Optional[int] = None,
    ) -> str:
        raise NotImplementedError
