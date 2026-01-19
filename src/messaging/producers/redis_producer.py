"""Redis producer for queue-based Redis operations."""

import logging
from typing import Any, Dict, Optional

from ..broker import get_broker, RabbitMQBroker
from ..models.message import RedisOperationMessage

logger = logging.getLogger(__name__)


class RedisProducer:
    """Producer for Redis operations."""
    
    def __init__(self):
        self.broker: Optional[RabbitMQBroker] = None
    
    async def initialize(self):
        """Initialize producer with broker connection."""
        self.broker = await get_broker()
    
    async def _ensure_broker(self):
        """Ensure broker is initialized."""
        if self.broker is None:
            await self.initialize()
        # Type assertion for Pylance
        assert self.broker is not None
    
    async def set_key(self, key: str, value: Any, ttl: Optional[int] = None, 
                      priority: int = 5) -> str:
        """Queue a Redis SET operation."""
        await self._ensure_broker()
        message = RedisOperationMessage(
            operation="set",
            data={
                "key": key,
                "value": value,
                "ttl": ttl
            },
            priority=priority
        )
        
        await self.broker.publish("redis-operations", message)
        logger.debug(f"Queued SET operation for key: {key}")
        return message.message_id
    
    async def get_key(self, key: str, priority: int = 5) -> str:
        """Queue a Redis GET operation."""
        await self._ensure_broker()
        message = RedisOperationMessage(
            operation="get",
            data={"key": key},
            priority=priority
        )
        
        await self.broker.publish("redis-operations", message)
        logger.debug(f"Queued GET operation for key: {key}")
        return message.message_id
    
    async def delete_key(self, key: str, priority: int = 3) -> str:
        """Queue a Redis DELETE operation."""
        await self._ensure_broker()
        message = RedisOperationMessage(
            operation="delete",
            data={"key": key},
            priority=priority
        )
        
        await self.broker.publish("redis-operations", message)
        logger.debug(f"Queued DELETE operation for key: {key}")
        return message.message_id
    
    async def setex_key(self, key: str, ttl: int, value: Any, priority: int = 5) -> str:
        """Queue a Redis SETEX operation."""
        await self._ensure_broker()
        message = RedisOperationMessage(
            operation="setex",
            data={
                "key": key,
                "ttl": ttl,
                "value": value
            },
            priority=priority
        )
        
        await self.broker.publish("redis-operations", message)
        logger.debug(f"Queued SETEX operation for key: {key} with TTL: {ttl}")
        return message.message_id
    
    async def incr_key(self, key: str, priority: int = 5) -> str:
        """Queue a Redis INCR operation."""
        await self._ensure_broker()
        message = RedisOperationMessage(
            operation="incr",
            data={"key": key},
            priority=priority
        )
        
        await self.broker.publish("redis-operations", message)
        logger.debug(f"Queued INCR operation for key: {key}")
        return message.message_id
    
    async def decr_key(self, key: str, priority: int = 5) -> str:
        """Queue a Redis DECR operation."""
        await self._ensure_broker()
        message = RedisOperationMessage(
            operation="decr",
            data={"key": key},
            priority=priority
        )
        
        await self.broker.publish("redis-operations", message)
        logger.debug(f"Queued DECR operation for key: {key}")
        return message.message_id
    
    async def expire_key(self, key: str, ttl: int, priority: int = 5) -> str:
        """Queue a Redis EXPIRE operation."""
        await self._ensure_broker()
        message = RedisOperationMessage(
            operation="expire",
            data={
                "key": key,
                "ttl": ttl
            },
            priority=priority
        )
        
        await self.broker.publish("redis-operations", message)
        logger.debug(f"Queued EXPIRE operation for key: {key} with TTL: {ttl}")
        return message.message_id
    
    async def hset_key(self, key: str, field: str, value: Any, priority: int = 5) -> str:
        """Queue a Redis HSET operation."""
        await self._ensure_broker()
        message = RedisOperationMessage(
            operation="hset",
            data={
                "key": key,
                "field": field,
                "value": value
            },
            priority=priority
        )
        
        await self.broker.publish("redis-operations", message)
        logger.debug(f"Queued HSET operation for key: {key}, field: {field}")
        return message.message_id
    
    async def hget_key(self, key: str, field: str, priority: int = 5) -> str:
        """Queue a Redis HGET operation."""
        await self._ensure_broker()
        message = RedisOperationMessage(
            operation="hget",
            data={
                "key": key,
                "field": field
            },
            priority=priority
        )
        
        await self.broker.publish("redis-operations", message)
        logger.debug(f"Queued HGET operation for key: {key}, field: {field}")
        return message.message_id
    
    async def sadd_key(self, key: str, member: Any, priority: int = 5) -> str:
        """Queue a Redis SADD operation."""
        await self._ensure_broker()
        message = RedisOperationMessage(
            operation="sadd",
            data={
                "key": key,
                "member": member
            },
            priority=priority
        )
        
        await self.broker.publish("redis-operations", message)
        logger.debug(f"Queued SADD operation for key: {key}")
        return message.message_id
    
    async def spop_key(self, key: str, priority: int = 5) -> str:
        """Queue a Redis SPOP operation."""
        await self._ensure_broker()
        message = RedisOperationMessage(
            operation="spop",
            data={"key": key},
            priority=priority
        )
        
        await self.broker.publish("redis-operations", message)
        logger.debug(f"Queued SPOP operation for key: {key}")
        return message.message_id
    
    async def zadd_key(self, key: str, score: float, member: Any, priority: int = 5) -> str:
        """Queue a Redis ZADD operation."""
        await self._ensure_broker()
        message = RedisOperationMessage(
            operation="zadd",
            data={
                "key": key,
                "score": score,
                "member": member
            },
            priority=priority
        )
        
        await self.broker.publish("redis-operations", message)
        logger.debug(f"Queued ZADD operation for key: {key}")
        return message.message_id
    
    async def zrange_key(self, key: str, start: int, stop: int, priority: int = 5) -> str:
        """Queue a Redis ZRANGE operation."""
        await self._ensure_broker()
        message = RedisOperationMessage(
            operation="zrange",
            data={
                "key": key,
                "start": start,
                "stop": stop
            },
            priority=priority
        )
        
        await self.broker.publish("redis-operations", message)
        logger.debug(f"Queued ZRANGE operation for key: {key}")
        return message.message_id
    
    async def flush_db(self, priority: int = 1) -> str:
        """Queue a Redis FLUSHDB operation (use with caution!)."""
        await self._ensure_broker()
        message = RedisOperationMessage(
            operation="flushdb",
            data={},
            priority=priority
        )
        
        await self.broker.publish("redis-operations", message)
        logger.warning("Queued FLUSHDB operation")
        return message.message_id
    
    async def aof_rewrite(self, priority: int = 1) -> str:
        """Queue a Redis AOF rewrite operation with rate limiting."""
        await self._ensure_broker()
        message = RedisOperationMessage(
            operation="aof_rewrite",
            data={},
            priority=priority,
            source="redis-maintenance"
        )
        
        await self.broker.publish("redis-operations", message)
        logger.info("Queued AOF rewrite operation")
        return message.message_id


# Global producer instance
_redis_producer_instance: Optional[RedisProducer] = None


async def get_redis_producer() -> RedisProducer:
    """Get or create global Redis producer instance."""
    global _redis_producer_instance
    
    if _redis_producer_instance is None:
        _redis_producer_instance = RedisProducer()
        await _redis_producer_instance.initialize()
    
    return _redis_producer_instance
