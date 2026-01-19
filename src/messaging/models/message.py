"""Message models for RabbitMQ communication."""

from pydantic import BaseModel, Field
from typing import Any, Dict, Optional
from datetime import datetime
import uuid


class MessageMetadata(BaseModel):
    """Metadata for message tracking."""
    
    retry_count: int = 0
    max_retries: int = 3
    created_at: datetime = Field(default_factory=datetime.utcnow)
    source: Optional[str] = None
    correlation_id: Optional[str] = None
    
    def should_retry(self) -> bool:
        """Check if message should be retried."""
        return self.retry_count < self.max_retries
    
    def increment_retry(self) -> None:
        """Increment retry count."""
        self.retry_count += 1


class MessagePayload(BaseModel):
    """Payload structure for messages."""
    
    operation: str
    data: Dict[str, Any]
    metadata: MessageMetadata = Field(default_factory=MessageMetadata)


class Message(BaseModel):
    """Base message structure."""
    
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source: str
    destination: str
    priority: int = Field(ge=1, le=10, default=5)
    ttl_seconds: int = 300
    payload: MessagePayload
    headers: Dict[str, str] = Field(default_factory=dict)
    
    model_config = {
        "json_encoders": {
            datetime: lambda v: v.isoformat()
        }
    }
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert message to dictionary."""
        # Use model_dump with mode='json' to handle datetime serialization
        return self.model_dump(mode='json')
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        """Create message from dictionary."""
        return cls(**data)


class RedisOperationMessage(Message):
    """Message for Redis operations."""
    
    def __init__(
        self,
        operation: str,
        data: Dict[str, Any],
        source: str = "redis-client",
        priority: int = 5
    ):
        """Initialize Redis operation message."""
        super().__init__(
            source=source,
            destination="redis-operations",
            priority=priority,
            payload=MessagePayload(
                operation=operation,
                data=data
            )
        )


class DocumentProcessingMessage(Message):
    """Message for document processing."""
    
    def __init__(
        self,
        file_path: str,
        operation: str = "document.ingest",
        source: str = "document-processor",
        priority: int = 3
    ):
        """Initialize document processing message."""
        super().__init__(
            source=source,
            destination="document-processing",
            priority=priority,
            ttl_seconds=3600,  # 1 hour TTL for document processing
            payload=MessagePayload(
                operation=operation,
                data={"file_path": file_path}
            )
        )


class VectorStorageMessage(Message):
    """Message for vector storage operations."""
    
    def __init__(
        self,
        operation: str,
        data: Dict[str, Any],
        source: str = "vector-processor",
        priority: int = 4
    ):
        """Initialize vector storage message."""
        super().__init__(
            source=source,
            destination="vector-storage",
            priority=priority,
            ttl_seconds=1800,  # 30 minutes TTL for vector operations
            payload=MessagePayload(
                operation=operation,
                data=data
            )
        )
