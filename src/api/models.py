"""Pydantic models compatible with OpenAI API schemas."""
from typing import List, Optional, Dict, Any, Literal, Union
from pydantic import BaseModel, Field
from datetime import datetime


# ===== Common Models =====

class Usage(BaseModel):
    """Token usage information."""
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


# ===== /v1/models =====

class Model(BaseModel):
    """Model information."""
    id: str
    object: Literal["model"] = "model"
    created: int = Field(default_factory=lambda: int(datetime.now().timestamp()))
    owned_by: str = "rag-local"


class ModelsResponse(BaseModel):
    """Response for /v1/models endpoint."""
    object: Literal["list"] = "list"
    data: List[Model]


# ===== /v1/chat/completions =====

class ChatMessage(BaseModel):
    """Chat message with role and content."""
    role: Literal["system", "user", "assistant", "function"]
    content: str
    name: Optional[str] = None
    function_call: Optional[Dict[str, Any]] = None


class ChatCompletionRequest(BaseModel):
    """Request for chat completion."""
    model: str
    messages: List[ChatMessage]
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
    top_p: Optional[float] = Field(default=1.0, ge=0.0, le=1.0)
    n: Optional[int] = Field(default=1, ge=1)
    stream: Optional[bool] = False
    stop: Optional[Union[str, List[str]]] = None
    max_tokens: Optional[int] = Field(default=1024, ge=1)
    presence_penalty: Optional[float] = Field(default=0.0, ge=-2.0, le=2.0)
    frequency_penalty: Optional[float] = Field(default=0.0, ge=-2.0, le=2.0)
    logit_bias: Optional[Dict[str, float]] = None
    user: Optional[str] = None
    top_k: Optional[int] = Field(default=5, ge=1)  # RAG-specific: number of documents to retrieve


class ChatCompletionChoice(BaseModel):
    """Single choice in chat completion response."""
    index: int
    message: ChatMessage
    finish_reason: Optional[Literal["stop", "length", "function_call", "content_filter"]] = "stop"


class ChatCompletionResponse(BaseModel):
    """Response for chat completion."""
    id: str
    object: Literal["chat.completion"] = "chat.completion"
    created: int = Field(default_factory=lambda: int(datetime.now().timestamp()))
    model: str
    choices: List[ChatCompletionChoice]
    usage: Usage
    system_fingerprint: Optional[str] = None


# ===== /v1/responses (modern endpoint) =====

class ResponseInput(BaseModel):
    """Input for response creation."""
    type: Literal["text"] = "text"
    text: str


class ResponseRequest(BaseModel):
    """Request for response creation (modern endpoint)."""
    model: str
    input: Union[str, List[ResponseInput]]
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=1024, ge=1)
    metadata: Optional[Dict[str, Any]] = None
    top_k: Optional[int] = Field(default=5, ge=1)  # RAG-specific


class ResponseOutput(BaseModel):
    """Output from response."""
    type: Literal["text"] = "text"
    text: str


class Source(BaseModel):
    """Source citation for RAG responses."""
    path: str
    relevance_score: float


class ResponseMetadata(BaseModel):
    """Metadata for RAG response."""
    retrieved_count: int
    sources: List[Source]
    query: str
    temperature: float
    max_tokens: int


class ResponseObject(BaseModel):
    """Response object (modern endpoint)."""
    id: str
    object: Literal["response"] = "response"
    created: int = Field(default_factory=lambda: int(datetime.now().timestamp()))
    model: str
    output: List[ResponseOutput]
    usage: Usage
    metadata: Optional[ResponseMetadata] = None


# ===== /v1/embeddings =====

class EmbeddingRequest(BaseModel):
    """Request for embeddings."""
    model: str = "text-embedding-ada-002"  # Default for compatibility
    input: Union[str, List[str]]
    encoding_format: Optional[Literal["float", "base64"]] = "float"
    user: Optional[str] = None


class Embedding(BaseModel):
    """Single embedding."""
    object: Literal["embedding"] = "embedding"
    embedding: List[float]
    index: int


class EmbeddingResponse(BaseModel):
    """Response for embeddings."""
    object: Literal["list"] = "list"
    data: List[Embedding]
    model: str
    usage: Usage


# ===== Error Response =====

class ErrorDetail(BaseModel):
    """Error detail."""
    message: str
    type: str
    param: Optional[str] = None
    code: Optional[str] = None


class ErrorResponse(BaseModel):
    """Error response."""
    error: ErrorDetail
