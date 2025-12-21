"""Identity generation for memory system.

Provides cryptographic generation of:
- user_id: SHA-256 stable identifier for users
- thread_id: HMAC-SHA256 unique identifier for conversations
"""
import hashlib
import hmac
import secrets
import time
from typing import Optional


def generate_user_id(
    client_info: Optional[dict] = None,
    stable_seed: Optional[str] = None
) -> str:
    """Generate stable SHA-256 user ID.

    Creates a persistent identifier for a user/client that remains
    consistent across sessions.

    Args:
        client_info: Optional dict with client metadata (IP, User-Agent, etc.)
        stable_seed: Optional seed for deterministic generation (testing only)

    Returns:
        Hex-encoded SHA-256 hash (64 characters)

    Example:
        >>> user_id = generate_user_id()
        >>> len(user_id)
        64
        >>> user_id = generate_user_id({"ip": "127.0.0.1", "ua": "Mozilla"})
    """
    hasher = hashlib.sha256()

    if stable_seed:
        # For testing/development: use provided seed
        hasher.update(stable_seed.encode('utf-8'))
    elif client_info:
        # Production: hash client information
        # Sort keys for deterministic ordering
        for key in sorted(client_info.keys()):
            value = str(client_info[key])
            hasher.update(f"{key}:{value}".encode('utf-8'))
    else:
        # Fallback: generate random stable ID
        # In production, this should be stored and reused
        random_seed = secrets.token_hex(32)
        hasher.update(random_seed.encode('utf-8'))

    return hasher.hexdigest()


def generate_thread_id(
    user_id: str,
    server_secret: str,
    conversation_seed: Optional[str] = None
) -> str:
    """Generate unique HMAC-SHA256 thread ID for a conversation.

    Creates a cryptographically secure, unpredictable identifier for
    a conversation thread.

    Args:
        user_id: User identifier (from generate_user_id)
        server_secret: Secret key from environment (THREAD_SECRET)
        conversation_seed: Optional seed (timestamp + random). If not provided,
                          generates new seed automatically.

    Returns:
        Hex-encoded HMAC-SHA256 hash (64 characters)

    Example:
        >>> thread_id = generate_thread_id(
        ...     user_id="abc123...",
        ...     server_secret="secret-key"
        ... )
        >>> len(thread_id)
        64

    Security:
        - Uses HMAC for authentication (prevents forgery)
        - Includes timestamp to ensure uniqueness
        - Unpredictable even with known user_id
    """
    # Generate conversation seed if not provided
    if conversation_seed is None:
        timestamp = str(time.time())
        random_component = secrets.token_hex(16)
        conversation_seed = f"{timestamp}:{random_component}"

    # Combine user_id and conversation_seed
    message = f"{user_id}:{conversation_seed}"

    # Generate HMAC-SHA256
    signature = hmac.new(
        key=server_secret.encode('utf-8'),
        msg=message.encode('utf-8'),
        digestmod=hashlib.sha256
    )

    return signature.hexdigest()


def validate_thread_id(thread_id: str) -> bool:
    """Validate thread ID format.

    Args:
        thread_id: Thread ID to validate

    Returns:
        True if valid format (64-char hex string)

    Example:
        >>> validate_thread_id("abc123" + "0" * 58)
        True
        >>> validate_thread_id("invalid")
        False
    """
    if not isinstance(thread_id, str):
        return False

    if len(thread_id) != 64:
        return False

    try:
        # Verify it's valid hexadecimal
        int(thread_id, 16)
        return True
    except ValueError:
        return False


def validate_user_id(user_id: str) -> bool:
    """Validate user ID format.

    Args:
        user_id: User ID to validate

    Returns:
        True if valid format (64-char hex string)

    Example:
        >>> validate_user_id("abc123" + "0" * 58)
        True
        >>> validate_user_id("invalid")
        False
    """
    return validate_thread_id(user_id)  # Same format
