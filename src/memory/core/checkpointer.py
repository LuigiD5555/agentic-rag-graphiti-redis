"""Redis checkpointer with intelligent TTL management.

Provides LangGraph checkpoint persistence with automatic TTL:
- Saves checkpoints with configurable TTL (default 48h)
- Extends TTL on access (touch on read)
- Automatic cleanup via Redis expiration
"""
import logging
from typing import Any, Optional

from langgraph.checkpoint.redis import RedisSaver


logger = logging.getLogger(__name__)


class TTLRedisSaver(RedisSaver):
    """Redis checkpoint saver with intelligent TTL management.

    Extends RedisSaver to add automatic TTL handling:
    - put(): Saves checkpoint and sets TTL
    - get(): Retrieves checkpoint and extends TTL (touch)

    This enables "touch on access" behavior where active conversations
    stay alive indefinitely (as long as accessed within TTL window).

    Example:
        >>> saver = TTLRedisSaver(
        ...     redis_url="redis://127.0.0.1:6379/0",
        ...     ttl_seconds=172800  # 48 hours
        ... )
        >>> # Save checkpoint - TTL starts
        >>> saver.put(config, checkpoint, metadata)
        >>> # Access checkpoint - TTL resets to 48h
        >>> checkpoint = saver.get(config)
    """

    def __init__(
        self,
        redis_url: str,
        ttl_seconds: int = 172800,  # 48 hours default
        **kwargs: Any
    ):
        """Initialize TTL Redis saver.

        Args:
            redis_url: Redis connection URL (e.g., "redis://127.0.0.1:6379/0")
            ttl_seconds: Time-to-live in seconds (default: 172800 = 48h)
            **kwargs: Additional arguments for RedisSaver
        """
        super().__init__(redis_url=redis_url, **kwargs)
        self.ttl = ttl_seconds
        logger.info(
            f"TTLRedisSaver initialized with TTL={ttl_seconds}s "
            f"({ttl_seconds / 3600:.1f}h)"
        )

    def put(
        self,
        config: dict,
        checkpoint: dict,
        metadata: dict,
        new_versions: Optional[dict] = None
    ) -> dict:
        """Save checkpoint with TTL.

        Args:
            config: LangGraph config (contains thread_id)
            checkpoint: Checkpoint data to save
            metadata: Checkpoint metadata
            new_versions: Optional version information

        Returns:
            Updated config

        Note:
            After saving, sets TTL on the Redis key. If conversation is
            never accessed again, it will auto-expire after TTL.
        """
        # Save checkpoint using parent implementation
        result = super().put(config, checkpoint, metadata, new_versions)

        # Apply TTL to checkpoint keys
        # RedisSaver uses keys like: langgraph:checkpoint:{thread_id}:*
        try:
            thread_id = config.get("configurable", {}).get("thread_id")
            if thread_id:
                # Set TTL on all keys for this thread
                pattern = f"langgraph:checkpoint:{thread_id}:*"
                keys = self._redis.keys(pattern)

                for key in keys:
                    self._redis.expire(key, self.ttl)

                logger.debug(
                    f"Set TTL={self.ttl}s on {len(keys)} keys for "
                    f"thread_id={thread_id[:8]}..."
                )
        except Exception as e:
            logger.error(f"Failed to set TTL: {e}", exc_info=True)

        return result

    def get(self, config: dict) -> Optional[dict]:
        """Retrieve checkpoint and extend TTL (touch on access).

        Args:
            config: LangGraph config (contains thread_id)

        Returns:
            Checkpoint data or None if not found

        Note:
            If checkpoint exists, this resets TTL to full duration.
            This implements "touch on access" - active conversations
            stay alive indefinitely.
        """
        # Retrieve checkpoint using parent implementation
        checkpoint = super().get(config)

        if checkpoint:
            # Extend TTL: reset to full duration
            try:
                thread_id = config.get("configurable", {}).get("thread_id")
                if thread_id:
                    pattern = f"langgraph:checkpoint:{thread_id}:*"
                    keys = self._redis.keys(pattern)

                    for key in keys:
                        self._redis.expire(key, self.ttl)

                    logger.debug(
                        f"Extended TTL={self.ttl}s on {len(keys)} keys for "
                        f"thread_id={thread_id[:8]}... (touch on access)"
                    )
            except Exception as e:
                logger.error(f"Failed to extend TTL: {e}", exc_info=True)

        return checkpoint

    def get_ttl(self, thread_id: str) -> Optional[int]:
        """Get remaining TTL for a thread.

        Args:
            thread_id: Thread ID to check

        Returns:
            Remaining TTL in seconds, or None if thread not found

        Example:
            >>> ttl = saver.get_ttl("abc123...")
            >>> if ttl:
            ...     print(f"Thread expires in {ttl / 3600:.1f} hours")
        """
        try:
            pattern = f"langgraph:checkpoint:{thread_id}:*"
            keys = self._redis.keys(pattern)

            if not keys:
                return None

            # Return TTL of first key (all should have same TTL)
            ttl = self._redis.ttl(keys[0])
            return ttl if ttl > 0 else None

        except Exception as e:
            logger.error(f"Failed to get TTL: {e}", exc_info=True)
            return None


def create_checkpointer(
    redis_host: str = "127.0.0.1",
    redis_port: int = 6379,
    redis_db: int = 0,
    ttl_seconds: int = 172800
) -> TTLRedisSaver:
    """Factory function to create TTL Redis checkpointer.

    Args:
        redis_host: Redis hostname
        redis_port: Redis port
        redis_db: Redis database number
        ttl_seconds: TTL in seconds (default: 48h)

    Returns:
        Configured TTLRedisSaver instance

    Example:
        >>> checkpointer = create_checkpointer(
        ...     redis_host="127.0.0.1",
        ...     redis_port=6379,
        ...     ttl_seconds=172800
        ... )
    """
    redis_url = f"redis://{redis_host}:{redis_port}/{redis_db}"
    return TTLRedisSaver(redis_url=redis_url, ttl_seconds=ttl_seconds)
