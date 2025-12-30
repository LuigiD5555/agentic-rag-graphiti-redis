"""Resilient Redis connection with automatic retries."""
import time
from typing import Optional
import redis
from src import logger


def create_redis_client_with_retry(
    host: str,
    port: int,
    password: str | None = None,
    decode_responses: bool = True,
    max_retries: int = 10,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    timeout: int = 5,
) -> redis.Redis:
    """
    Create a Redis client with exponential backoff retry logic.

    Args:
        host: Redis host address
        port: Redis port number
        decode_responses: Whether to decode responses as strings
        max_retries: Maximum number of connection attempts
        initial_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries in seconds
        timeout: Socket timeout in seconds

    Returns:
        Connected Redis client

    Raises:
        redis.ConnectionError: If connection fails after all retries
    """
    delay = initial_delay
    last_error: Optional[Exception] = None

    for attempt in range(1, max_retries + 1):
        try:
            logger.info(
                "Attempting to connect to Redis at %s:%s (attempt %d/%d)",
                host, port, attempt, max_retries
            )

            client = redis.Redis(
                host=host,
                port=port,
                password=password,
                decode_responses=decode_responses,
                socket_timeout=timeout,
                socket_connect_timeout=timeout,
            )

            # Test connection with PING
            client.ping()

            logger.info("Successfully connected to Redis at %s:%s", host, port)
            return client

        except (redis.ConnectionError, redis.TimeoutError, redis.BusyLoadingError, OSError) as e:
            last_error = e

            if attempt == max_retries:
                logger.error(
                    "Failed to connect to Redis at %s:%s after %d attempts. "
                    "Last error: %s",
                    host, port, max_retries, e
                )
                break

            logger.warning(
                "Redis connection attempt %d/%d failed: %s. "
                "Retrying in %.1f seconds...",
                attempt, max_retries, e, delay
            )

            time.sleep(delay)

            # Exponential backoff with cap
            delay = min(delay * 2, max_delay)

    # If we get here, all retries failed
    error_msg = (
        f"Could not connect to Redis at {host}:{port} after {max_retries} attempts. "
        f"Last error: {last_error}"
    )
    raise redis.ConnectionError(error_msg) from last_error


__all__ = ["create_redis_client_with_retry"]
