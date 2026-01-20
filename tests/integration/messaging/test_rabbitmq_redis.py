"""Pytest coverage for RabbitMQ Redis queue integration."""

import pytest


pytestmark = [
    pytest.mark.integration,
]


@pytest.mark.asyncio
async def test_rabbitmq_broker_publish():
    from src.messaging.broker import RabbitMQBroker
    from src.messaging.config import config
    from src.messaging.models.message import RedisOperationMessage

    broker = RabbitMQBroker()
    await broker.connect()
    try:
        message = RedisOperationMessage(
            operation="set",
            data={"key": "test:key", "value": "test_value", "ttl": 60},
        )
        success = await broker.publish(config.redis_queue, message)
        assert success is True
    finally:
        await broker.disconnect()


@pytest.mark.asyncio
async def test_redis_producer_queues_operations():
    from src.messaging.producers.redis_producer import get_redis_producer

    producer = await get_redis_producer()

    message_id = await producer.set_key("test:session:123", "user_data", ttl=3600)
    assert isinstance(message_id, str)

    message_id = await producer.get_key("test:session:123")
    assert isinstance(message_id, str)

    message_id = await producer.aof_rewrite()
    assert isinstance(message_id, str)
