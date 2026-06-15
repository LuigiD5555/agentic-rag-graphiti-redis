"""Pydantic models for file upload API."""
from typing import Optional, List
from pydantic import BaseModel, Field


class FileUploadResponse(BaseModel):
    """Response model for file upload (OpenAI-compatible)."""

    id: str = Field(..., description="Unique file identifier")
    object: str = Field(default="file", description="Object type")
    bytes: int = Field(..., description="File size in bytes")
    created_at: int = Field(..., description="Unix timestamp of creation")
    filename: str = Field(..., description="Original filename")
    purpose: str = Field(default="assistants", description="File purpose")
    status: str = Field(default="processed", description="Processing status")

    # Custom fields for temporal RAG
    temporal: bool = Field(default=True, description="Whether file is in temporal storage")
    tenant: str = Field(..., description="Weaviate tenant name")
    chunks: int = Field(..., description="Number of chunks created")
    upload_count: int = Field(..., description="Total times this file has been uploaded")
    should_promote: bool = Field(default=False, description="Whether file should be promoted")


class FileListResponse(BaseModel):
    """Response model for listing files."""

    object: str = Field(default="list", description="Object type")
    data: List[FileUploadResponse] = Field(default_factory=list, description="List of files")


class FileDeleteResponse(BaseModel):
    """Response model for file deletion."""

    id: str = Field(..., description="File identifier")
    object: str = Field(default="file", description="Object type")
    deleted: bool = Field(..., description="Whether deletion was successful")


class PromotionRequest(BaseModel):
    """Request model for manual file promotion."""

    mode: str = Field(..., description="Promotion mode: 'full' or 'pareto'")


class PromotionResponse(BaseModel):
    """Response model for file promotion."""

    file_id: str = Field(..., description="File identifier")
    mode: str = Field(..., description="Promotion mode used")
    chunks_promoted: int = Field(..., description="Number of chunks promoted")
    success: bool = Field(..., description="Whether promotion was successful")
    message: str = Field(..., description="Status message")
