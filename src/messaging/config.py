"""RabbitMQ configuration settings."""

from pydantic_settings import BaseSettings


class RabbitMQConfig(BaseSettings):
    """RabbitMQ configuration settings."""
    
    host: str = "127.0.0.1"
    port: int = 5672
    username: str = "admin"
    password: str = "change-me-rabbitmq"
    vhost: str = "/rag"
    heartbeat: int = 60
    connection_timeout: int = 30
    channel_max: int = 100
    management_port: int = 15672
    
    # Queue configurations
    document_queue: str = "document-processing"
    vector_queue: str = "vector-storage"
    notification_queue: str = "system-notifications"
    
    # Exchange configurations
    topic_exchange: str = "processing.topic"
    fanout_exchange: str = "notifications.fanout"
    
    # Dead letter exchanges
    processing_dlx: str = "processing.dlx"
    storage_dlx: str = "storage.dlx"
    
    # Consumer configurations
    prefetch_count: int = 10
    max_concurrent_consumers: int = 5
    
    # Feature flag
    enabled: bool = True
    
    model_config = {
        "env_prefix": "RABBITMQ_",
        "env_file": ".env",
        "extra": "allow"  # Allow extra fields from .env
    }


# Global configuration instance
config = RabbitMQConfig()
