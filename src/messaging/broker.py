"""RabbitMQ message broker implementation."""

import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, Optional, Callable

from .config import config
from .models.message import Message as MessageModel

logger = logging.getLogger(__name__)


class MessageBroker(ABC):
    """Abstract base class for message brokers."""
    
    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the broker."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the broker."""
        pass
    
    @abstractmethod
    async def publish(self, queue: str, message: MessageModel) -> bool:
        """Publish a message to a queue."""
        pass
    
    @abstractmethod
    async def consume(self, queue: str, callback: Callable) -> None:
        """Start consuming messages from a queue."""
        pass


class RabbitMQBroker(MessageBroker):
    """RabbitMQ implementation of message broker."""
    
    def __init__(self):
        self.connection = None
        self.channel = None
        self.exchanges: Dict[str, any] = {}
        self.queues: Dict[str, any] = {}
        
    async def connect(self) -> None:
        """Establish connection to RabbitMQ."""
        if not config.enabled:
            logger.info("RabbitMQ is disabled, skipping connection")
            return
            
        try:
            # Try to import aio_pika
            import aio_pika
            from aio_pika import ExchangeType
            
            # Create connection
            self.connection = await aio_pika.connect_robust(
                host=config.host,
                port=config.port,
                login=config.username,
                password=config.password,
                virtualhost=config.vhost,
                heartbeat=config.heartbeat,
                timeout=config.connection_timeout
            )
            
            # Create channel
            self.channel = await self.connection.channel()
            
            # Set prefetch count
            await self.channel.set_qos(prefetch_count=config.prefetch_count)
            
            # Declare exchanges
            await self._declare_exchanges()
            
            # Declare queues
            await self._declare_queues()
            
            logger.info("Connected to RabbitMQ successfully")
            
        except ImportError:
            logger.error("aio_pika is not installed. Please install it with: pip install aio-pika")
        except Exception as e:
            logger.error(f"Failed to connect to RabbitMQ: {e}")
            raise
    
    async def disconnect(self) -> None:
        """Close connection to RabbitMQ."""
        if self.connection:
            await self.connection.close()
            logger.info("Disconnected from RabbitMQ")
    
    async def _declare_exchanges(self) -> None:
        """Declare all required exchanges."""
        from aio_pika import ExchangeType
        
        # Direct exchange for Redis operations
        self.exchanges["direct"] = await self.channel.declare_exchange(
            name=config.direct_exchange,
            type=ExchangeType.DIRECT,
            durable=True
        )
        
        # Topic exchange for processing
        self.exchanges["topic"] = await self.channel.declare_exchange(
            name=config.topic_exchange,
            type=ExchangeType.TOPIC,
            durable=True
        )
        
        # Fanout exchange for notifications
        self.exchanges["fanout"] = await self.channel.declare_exchange(
            name=config.fanout_exchange,
            type=ExchangeType.FANOUT,
            durable=True
        )
    
    async def _declare_queues(self) -> None:
        """Declare all required queues."""
        # Redis operations queue
        self.queues["redis"] = await self.channel.declare_queue(
            name=config.redis_queue,
            durable=True,
            arguments={
                "x-max-priority": 10
            }
        )
        await self.queues["redis"].bind(
            exchange=self.exchanges["direct"],
            routing_key="redis.*"
        )
        
        # Document processing queue
        self.queues["document"] = await self.channel.declare_queue(
            name=config.document_queue,
            durable=True,
            arguments={
                "x-max-priority": 10,
                "x-message-ttl": 3600000  # 1 hour in milliseconds
            }
        )
        await self.queues["document"].bind(
            exchange=self.exchanges["topic"],
            routing_key="document.*"
        )
        
        # Vector storage queue
        self.queues["vector"] = await self.channel.declare_queue(
            name=config.vector_queue,
            durable=True,
            arguments={
                "x-max-priority": 10,
                "x-message-ttl": 1800000  # 30 minutes in milliseconds
            }
        )
        await self.queues["vector"].bind(
            exchange=self.exchanges["topic"],
            routing_key="vector.*"
        )
        
        # System notifications queue
        self.queues["notification"] = await self.channel.declare_queue(
            name=config.notification_queue,
            durable=True,
            arguments={
                "x-max-priority": 10
            }
        )
        await self.queues["notification"].bind(
            exchange=self.exchanges["fanout"]
        )
    
    async def publish(self, queue: str, message: MessageModel) -> bool:
        """Publish a message to a queue."""
        if not config.enabled:
            logger.warning("RabbitMQ is disabled, message not published")
            return False
            
        try:
            from aio_pika import Message, DeliveryMode
            
            # Convert message to JSON
            message_data = json.dumps(message.to_dict())
            
            # Determine exchange and routing key based on queue
            if queue == config.redis_queue:
                exchange = self.exchanges["direct"]
                routing_key = f"redis.{message.payload.operation}"
            elif queue == config.document_queue:
                exchange = self.exchanges["topic"]
                routing_key = f"document.{message.payload.operation}"
            elif queue == config.vector_queue:
                exchange = self.exchanges["topic"]
                routing_key = f"vector.{message.payload.operation}"
            elif queue == config.notification_queue:
                exchange = self.exchanges["fanout"]
                routing_key = ""
            else:
                raise ValueError(f"Unknown queue: {queue}")
            
            # Create RabbitMQ message
            rabbitmq_message = Message(
                body=message_data.encode(),
                delivery_mode=DeliveryMode.PERSISTENT,
                priority=message.priority,
                headers={
                    "message_id": message.message_id,
                    "correlation_id": message.correlation_id,
                    "timestamp": message.timestamp.isoformat(),
                    "source": message.source,
                    "destination": message.destination
                }
            )
            
            # Publish message
            await exchange.publish(
                rabbitmq_message,
                routing_key=routing_key
            )
            
            logger.debug(f"Published message {message.message_id} to {queue}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to publish message to {queue}: {e}")
            return False
    
    async def consume(self, queue: str, callback: Callable) -> None:
        """Start consuming messages from a queue."""
        if not config.enabled:
            logger.warning("RabbitMQ is disabled, not consuming messages")
            return
            
        try:
            # Get queue
            if queue == config.redis_queue:
                rabbitmq_queue = self.queues["redis"]
            elif queue == config.document_queue:
                rabbitmq_queue = self.queues["document"]
            elif queue == config.vector_queue:
                rabbitmq_queue = self.queues["vector"]
            elif queue == config.notification_queue:
                rabbitmq_queue = self.queues["notification"]
            else:
                raise ValueError(f"Unknown queue: {queue}")
            
            # Start consuming
            async with rabbitmq_queue.iterator() as queue_iter:
                async for rabbitmq_message in queue_iter:
                    try:
                        async with rabbitmq_message.process():
                            # Parse message
                            message_data = json.loads(rabbitmq_message.body.decode())
                            message = MessageModel.from_dict(message_data)
                            
                            # Process message
                            result = await callback(message)
                            
                            # Handle result
                            if result and isinstance(result, dict) and result.get("success"):
                                logger.debug(f"Processed message {message.message_id} successfully")
                            else:
                                logger.warning(f"Message {message.message_id} processing failed")
                                await rabbitmq_message.reject(requeue=False)
                                
                    except Exception as e:
                        logger.error(f"Error processing message: {e}")
                        await rabbitmq_message.reject(requeue=False)
                        
        except Exception as e:
            logger.error(f"Error in consumer for queue {queue}: {e}")
            raise


# Global broker instance
_broker_instance: Optional[RabbitMQBroker] = None


async def get_broker() -> RabbitMQBroker:
    """Get or create global broker instance."""
    global _broker_instance
    
    if _broker_instance is None:
        _broker_instance = RabbitMQBroker()
        await _broker_instance.connect()
    
    return _broker_instance


async def close_broker() -> None:
    """Close global broker instance."""
    global _broker_instance
    
    if _broker_instance:
        await _broker_instance.disconnect()
        _broker_instance = None
