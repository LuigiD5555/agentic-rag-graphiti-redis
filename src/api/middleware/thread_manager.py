"""Thread ID management middleware for memory system."""
import hashlib
import json
import logging
import os
from typing import Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from src.memory.core.identifiers import (
    generate_user_id,
    generate_thread_id,
    validate_thread_id,
)
from src.rag.conf import Config

_config = Config()

logger = logging.getLogger(__name__)


def _extract_conversation_id_from_body(body_bytes: bytes, user_id: str) -> Optional[str]:
    """Extract stable conversation ID from request body.

    For Open WebUI and other clients that send conversation history,
    we generate a stable ID based on:
    1. First user message in the conversation (if available)
    2. User ID + timestamp (fallback)

    Args:
        body_bytes: Raw request body
        user_id: User identifier

    Returns:
        Stable conversation ID (64-char hex) or None if extraction fails
    """
    try:
        body = json.loads(body_bytes.decode('utf-8'))
        messages = body.get('messages', [])

        if not messages:
            return None

        # Find the first user message in the conversation
        first_user_msg = None
        for msg in messages:
            if isinstance(msg, dict) and msg.get('role') == 'user':
                first_user_msg = msg.get('content', '')
                break

        if not first_user_msg:
            return None

        # Generate stable hash from user_id + first message
        # This ensures same conversation has same ID across requests
        conversation_seed = f"{user_id}:{first_user_msg}"
        hasher = hashlib.sha256()
        hasher.update(conversation_seed.encode('utf-8'))

        stable_id = hasher.hexdigest()
        logger.debug(f"Extracted stable conversation ID from first message (len={len(first_user_msg)})")
        return stable_id

    except Exception as e:
        logger.warning(f"Failed to extract conversation ID from body: {e}")
        return None


class ThreadManagerMiddleware(BaseHTTPMiddleware):
    """Middleware to manage thread IDs for conversation memory.

    Extracts or generates thread_id and user_id for each request,
    making them available via request.state.
    """

    THREAD_ID_HEADER = "X-Thread-ID"
    USER_ID_HEADER = "X-User-ID"

    def __init__(self, app, server_secret: Optional[str] = None):
        """Initialize thread manager middleware.

        Args:
            app: FastAPI application
            server_secret: Secret for HMAC thread ID generation
        """
        super().__init__(app)
        self.server_secret = server_secret or os.getenv(
            "THREAD_SECRET",
            "change-this-secret-in-production"
        )
        logger.info("ThreadManagerMiddleware initialized")

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint
    ) -> Response:
        """Process request and inject thread/user IDs.

        Args:
            request: Incoming request
            call_next: Next middleware/handler

        Returns:
            Response with thread ID header
        """
        # Debug: Log all headers for troubleshooting (temporary for diagnosis)
        logger.debug(f"Request headers: {dict(request.headers)}")

        # Extract or generate user_id
        user_id = request.headers.get(self.USER_ID_HEADER)

        if not user_id:
            # Generate from client info
            client_info = {
                "ip": request.client.host if request.client else "unknown",
                "ua": request.headers.get("user-agent", "unknown")
            }
            user_id = generate_user_id(client_info=client_info)
            logger.debug(f"Generated user_id: {user_id[:16]}...")

        # Extract or generate thread_id
        thread_id = request.headers.get(self.THREAD_ID_HEADER)

        if thread_id and validate_thread_id(thread_id):
            # Valid existing thread from header
            logger.debug(f"Using existing thread_id from header: {thread_id[:16]}...")
        else:
            # Try to extract conversation ID from request body
            # (for Open WebUI and other clients that send conversation history)
            body_bytes = await request.body()

            # Make body available again for endpoint processing
            async def receive():
                return {"type": "http.request", "body": body_bytes}

            request._receive = receive

            # Extract stable conversation ID from first message
            conversation_id = _extract_conversation_id_from_body(body_bytes, user_id)

            if conversation_id:
                # Use stable conversation ID
                thread_id = conversation_id
                logger.info(f"Using stable conversation ID from first message: {thread_id[:16]}...")
            else:
                # Fallback: generate new random thread
                thread_id = generate_thread_id(
                    user_id=user_id,
                    server_secret=self.server_secret
                )
                logger.debug(f"Generated new thread_id: {thread_id[:16]}...")

        # Inject into request state
        request.state.user_id = user_id
        request.state.thread_id = thread_id

        # Process request
        response = await call_next(request)

        # Add thread ID to response headers
        response.headers[self.THREAD_ID_HEADER] = thread_id
        response.headers[self.USER_ID_HEADER] = user_id

        return response


def get_thread_id(request: Request) -> str:
    """Dependency to extract thread ID from request.

    Args:
        request: FastAPI request

    Returns:
        Thread ID string

    Raises:
        ValueError: If thread ID not found in request state
    """
    thread_id = getattr(request.state, "thread_id", None)
    if not thread_id:
        raise ValueError("Thread ID not found in request state")
    return thread_id


def get_user_id(request: Request) -> str:
    """Dependency to extract user ID from request.

    Args:
        request: FastAPI request

    Returns:
        User ID string

    Raises:
        ValueError: If user ID not found in request state
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise ValueError("User ID not found in request state")
    return user_id