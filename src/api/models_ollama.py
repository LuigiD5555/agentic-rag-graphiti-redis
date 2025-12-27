"""Pydantic models for Ollama-like API endpoints."""
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union, Literal

from pydantic import BaseModel, Field


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OllamaMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class OllamaOptions(BaseModel):
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    top_k: Optional[int] = Field(default=None, ge=1)
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    max_tokens: Optional[int] = Field(default=None, ge=1)
    num_predict: Optional[int] = Field(default=None, ge=1)


class OllamaRagOptions(BaseModel):
    enabled: Optional[bool] = True
    filters: Optional[Dict[str, Any]] = None
    include_sources: Optional[bool] = True


class OllamaGenerateRequest(BaseModel):
    model: str
    prompt: str
    system: Optional[str] = None
    stream: Optional[bool] = False
    options: Optional[OllamaOptions] = None
    rag: Optional[OllamaRagOptions] = None


class OllamaChatRequest(BaseModel):
    model: str
    messages: List[OllamaMessage]
    stream: Optional[bool] = False
    options: Optional[OllamaOptions] = None
    rag: Optional[OllamaRagOptions] = None


class OllamaGenerateResponse(BaseModel):
    model: str
    created_at: str = Field(default_factory=_utc_now)
    response: str
    done: bool = True
    sources: Optional[List[Dict[str, Any]]] = None
    context: Optional[Any] = None


class OllamaChatResponse(BaseModel):
    model: str
    created_at: str = Field(default_factory=_utc_now)
    message: OllamaMessage
    done: bool = True
    sources: Optional[List[Dict[str, Any]]] = None
    context: Optional[Any] = None


class OllamaEmbeddingsRequest(BaseModel):
    model: str
    input: Union[str, List[str]]


class OllamaEmbeddingsResponse(BaseModel):
    model: str
    embeddings: List[List[float]]


class OllamaPullRequest(BaseModel):
    name: str
    stream: Optional[bool] = False


class OllamaTagModel(BaseModel):
    name: str
    model: Optional[str] = None  # Alias for name, some clients expect this
    modified_at: str = Field(default_factory=_utc_now)
    size: int = 0  # Model size in bytes (0 for unknown)
    digest: str = ""  # Model digest/hash (empty for unknown)
    details: Dict[str, Any] = Field(default_factory=dict)


class OllamaTagsResponse(BaseModel):
    models: List[OllamaTagModel]


class RagQueryRequest(BaseModel):
    query: str
    top_k: Optional[int] = Field(default=None, ge=1)
    filters: Optional[Dict[str, Any]] = None
    include_sources: Optional[bool] = True
    temperature: Optional[float] = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=1024, ge=1)
    system: Optional[str] = None


class RagQueryResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RagIngestRequest(BaseModel):
    paths: List[str]
    dry_run: Optional[bool] = False
    per_file: Optional[bool] = False
    max_files: Optional[int] = 0
    streaming: Optional[bool] = None
    allowed_extensions: Optional[List[str]] = None
    excluded_dirs: Optional[List[str]] = None
    excluded_globs: Optional[List[str]] = None
    follow_symlinks: Optional[bool] = False
    enabled_paths: Optional[List[str]] = None
    scan_progress_every: Optional[int] = 0


class RagIngestResponse(BaseModel):
    status: str
    ingested: int
    failed: int
    candidates: Optional[int] = None


class RagToolRequest(BaseModel):
    input_path: str
    output_format: Optional[str] = None
    max_size_mb: Optional[int] = None
    language: Optional[str] = None


class RagToolResponse(BaseModel):
    success: bool
    output_path: Optional[str] = None
    output_dir: Optional[str] = None
    file_count: Optional[int] = None
    total_size_mb: Optional[float] = None
    error: Optional[str] = None


class RagFileLocationResponse(BaseModel):
    file_id: str
    path: Optional[str] = None


class RagFileMetadataResponse(BaseModel):
    file_id: str
    metadata: Optional[Dict[str, Any]] = None
