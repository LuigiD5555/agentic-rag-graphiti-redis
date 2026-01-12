"""File upload router for temporal RAG (OpenAI-compatible /v1/files endpoint)."""
import logging
import os
import time
import uuid
from typing import Optional

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, Header
import redis
import weaviate

from src.api.files.models import (
    FileUploadResponse,
    FileListResponse,
    FileDeleteResponse,
    PromotionRequest,
    PromotionResponse,
)
from src.api.files.tracking import FileTracker, create_file_tracker
from src.workflows.query.temporal.tenant_manager import (
    TemporalTenantManager,
    create_temporal_tenant_manager,
)
from src.workflows.ingestion.orchestrator import IngestionOrchestrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/files", tags=["files"])

_file_tracker: Optional[FileTracker] = None
_tenant_manager: Optional[TemporalTenantManager] = None
_ingestion_orchestrator: Optional[IngestionOrchestrator] = None
_weaviate_client: Optional[weaviate.WeaviateClient] = None
_redis_client: Optional[redis.Redis] = None
_file_promoter = None
_pareto_analyzer = None


def get_file_tracker() -> FileTracker:
    """Get FileTracker instance."""
    if _file_tracker is None:
        raise RuntimeError("FileTracker not initialized")
    return _file_tracker


def get_tenant_manager() -> TemporalTenantManager:
    """Get TemporalTenantManager instance."""
    if _tenant_manager is None:
        raise RuntimeError("TemporalTenantManager not initialized")
    return _tenant_manager


def get_ingestion_orchestrator() -> IngestionOrchestrator:
    """Get IngestionOrchestrator instance."""
    if _ingestion_orchestrator is None:
        raise RuntimeError("IngestionOrchestrator not initialized")
    return _ingestion_orchestrator


def extract_thread_id(x_thread_id: Optional[str] = Header(None)) -> str:
    """Extract thread_id from headers.

    Args:
        x_thread_id: Thread ID from X-Thread-ID header

    Returns:
        Thread ID

    Raises:
        HTTPException: If thread_id is not provided
    """
    if not x_thread_id:
        raise HTTPException(
            status_code=400,
            detail="X-Thread-ID header is required for file uploads",
        )
    return x_thread_id


@router.post("", response_model=FileUploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    purpose: str = Form(default="assistants"),
    thread_id: str = Depends(extract_thread_id),
    tracker: FileTracker = Depends(get_file_tracker),
    tenant_manager: TemporalTenantManager = Depends(get_tenant_manager),
    ingestion_orch: IngestionOrchestrator = Depends(get_ingestion_orchestrator),
):
    """Upload a file for temporal RAG.

    The file is ingested into a temporary tenant (temp_{thread_id}) in Weaviate.
    If the file is uploaded multiple times, it may be auto-promoted to permanent storage.

    Args:
        file: Uploaded file
        purpose: File purpose (default: "assistants")
        thread_id: Thread identifier (from X-Thread-ID header)
        tracker: FileTracker instance
        tenant_manager: TemporalTenantManager instance
        ingestion_orch: IngestionOrchestrator instance

    Returns:
        FileUploadResponse with file metadata
    """
    try:
        content = await file.read()
        file_size = len(content)

        max_size = _config.TEMPORAL_FILE_MAX_SIZE_MB * 1024 * 1024
        if file_size > max_size:
            raise HTTPException(
                status_code=413,
                detail=f"File too large. Maximum size: {_config.TEMPORAL_FILE_MAX_SIZE_MB}MB",
            )

        file_hash = tracker.compute_file_hash(content)
        logger.info(f"Uploading file: {file.filename} (hash={file_hash[:8]}..., size={file_size})")

        file_info = tracker.get_file_info(file_hash)
        if file_info and int(file_info.get("upload_count", 0)) >= tracker.promotion_threshold:
            if file_info.get("promoted") == "1":
                logger.info(f"File {file_hash[:8]}... already promoted, using permanent KB")

        tenant_name = tenant_manager.get_or_create_temporal_tenant(thread_id)

        file_id = f"file_{uuid.uuid4().hex[:16]}"
        temp_dir = _config.PREPROCESSING_WORK_DIR
        os.makedirs(temp_dir, exist_ok=True)

        temp_file_path = os.path.join(temp_dir, f"{file_id}_{file.filename}")

        with open(temp_file_path, "wb") as f:
            f.write(content)

        try:
            original_tenant = ingestion_orch._config.WEAVIATE_DEFAULT_TENANT
            ingestion_orch._config.WEAVIATE_DEFAULT_TENANT = tenant_name

            from src.workflows.ingestion.options import IngestionOptions

            ingestion_options = IngestionOptions(
                root_paths=[temp_file_path],
                maximum_files=1,
                per_file_mode=True,
            )

            result = ingestion_orch.run_with_report(ingestion_options)

            ingestion_orch._config.WEAVIATE_DEFAULT_TENANT = original_tenant

            chunk_ids = [f"{file_id}_chunk_{i}" for i in range(result.get("ingested", 0))]

            tracking_result = tracker.track_file_upload(
                file_hash=file_hash,
                thread_id=thread_id,
                file_id=file_id,
                filename=file.filename,
                chunk_ids=chunk_ids,
            )

            return FileUploadResponse(
                id=file_id,
                bytes=file_size,
                created_at=int(time.time()),
                filename=file.filename,
                purpose=purpose,
                status="processed",
                temporal=True,
                tenant=tenant_name,
                chunks=result.get("ingested", 0),
                upload_count=tracking_result["upload_count"],
                should_promote=tracking_result["should_auto_promote"],
            )

        finally:
            if os.path.exists(temp_file_path):
                os.remove(temp_file_path)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File upload failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"File upload failed: {str(e)}")


@router.get("", response_model=FileListResponse)
async def list_files(
    thread_id: Optional[str] = None,
    tracker: FileTracker = Depends(get_file_tracker),
):
    """List uploaded files.

    Args:
        thread_id: Optional thread ID to filter files
        tracker: FileTracker instance

    Returns:
        FileListResponse with list of files
    """
    try:
        if thread_id:
            file_ids = tracker.list_temporal_files(thread_id)

            files = []
            for file_id in file_ids:
                file_info = tracker.get_temporal_file_info(thread_id, file_id)
                if file_info:
                    files.append(
                        FileUploadResponse(
                            id=file_id,
                            bytes=0,
                            created_at=int(float(file_info.get("uploaded_at", 0))),
                            filename=file_info.get("filename", "unknown"),
                            purpose="assistants",
                            status="processed",
                            temporal=True,
                            tenant=f"temp_{thread_id}",
                            chunks=len(file_info.get("chunk_ids", [])),
                            upload_count=int(file_info.get("query_count", 0)),
                            should_promote=False,
                        )
                    )

            return FileListResponse(data=files)

        else:
            return FileListResponse(data=[])

    except Exception as e:
        logger.error(f"Failed to list files: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list files: {str(e)}")


@router.delete("/{file_id}", response_model=FileDeleteResponse)
async def delete_file(
    file_id: str,
    thread_id: str = Depends(extract_thread_id),
    tracker: FileTracker = Depends(get_file_tracker),
):
    """Delete a temporal file.

    Args:
        file_id: File identifier
        thread_id: Thread identifier
        tracker: FileTracker instance

    Returns:
        FileDeleteResponse
    """
    try:
        file_info = tracker.get_temporal_file_info(thread_id, file_id)

        if not file_info:
            raise HTTPException(status_code=404, detail="File not found")

        temp_file_key = f"temp_file:{thread_id}:{file_id}"
        _redis_client.delete(temp_file_key)
        _redis_client.delete(f"{temp_file_key}:chunk_scores")
        _redis_client.srem(f"temp_files:{thread_id}", file_id)

        logger.info(f"Deleted file {file_id} from thread {thread_id}")

        return FileDeleteResponse(
            id=file_id,
            deleted=True,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")


@router.post("/{file_id}/promote", response_model=PromotionResponse)
async def promote_file(
    file_id: str,
    request: PromotionRequest,
    thread_id: str = Depends(extract_thread_id),
    tracker: FileTracker = Depends(get_file_tracker),
):
    """Manually promote a file to permanent storage.

    Args:
        file_id: File identifier
        request: Promotion request (mode: 'full' or 'pareto')
        thread_id: Thread identifier
        tracker: FileTracker instance

    Returns:
        PromotionResponse
    """
    try:
        file_info = tracker.get_temporal_file_info(thread_id, file_id)

        if not file_info:
            raise HTTPException(status_code=404, detail="File not found")

        if _file_promoter is None:
            raise HTTPException(status_code=500, detail="File promoter not initialized")

        from src.workflows.query.temporal.promotion import PromotionMode

        mode = PromotionMode.PARETO if request.mode == "pareto" else PromotionMode.FULL

        result = _file_promoter.promote_file(
            thread_id=thread_id,
            file_id=file_id,
            mode=mode,
        )

        if not result.get("success"):
            raise HTTPException(
                status_code=500,
                detail=result.get("error", "Promotion failed"),
            )

        return PromotionResponse(
            file_id=file_id,
            mode=request.mode,
            chunks_promoted=result["chunks_promoted"],
            success=True,
            message=result["message"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to promote file: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to promote file: {str(e)}")


def initialize_files_router(
    weaviate_client: weaviate.WeaviateClient,
    redis_client: redis.Redis,
    ingestion_orchestrator: IngestionOrchestrator,
    collection_name: str,
    default_tenant: Optional[str] = None,
):
    """Initialize the files router with required dependencies.

    Args:
        weaviate_client: Weaviate client instance
        redis_client: Redis client instance
        ingestion_orchestrator: IngestionOrchestrator instance
        collection_name: Weaviate collection name
        default_tenant: Default (permanent) tenant name
    """
    global _file_tracker, _tenant_manager, _ingestion_orchestrator, _weaviate_client, _redis_client, _file_promoter, _pareto_analyzer

    _file_tracker = create_file_tracker(
        redis_client=redis_client,
        promotion_threshold=_config.TEMPORAL_PROMOTION_THRESHOLD,
        pareto_min_queries=_config.TEMPORAL_PARETO_MIN_QUERIES,
    )

    _tenant_manager = create_temporal_tenant_manager(
        weaviate_client=weaviate_client,
        collection_name=collection_name,
        ttl_seconds=_config.TEMPORAL_TENANT_TTL,
    )

    from src.workflows.query.temporal.pareto import create_pareto_analyzer
    _pareto_analyzer = create_pareto_analyzer(
        redis_client=redis_client,
        top_percent=_config.TEMPORAL_PARETO_TOP_PERCENT,
        min_queries=_config.TEMPORAL_PARETO_MIN_QUERIES,
    )

    from src.workflows.query.temporal.promotion import create_file_promoter
    _file_promoter = create_file_promoter(
        weaviate_client=weaviate_client,
        redis_client=redis_client,
        collection_name=collection_name,
        default_tenant=default_tenant,
        pareto_analyzer=_pareto_analyzer,
    )

    _ingestion_orchestrator = ingestion_orchestrator
    _weaviate_client = weaviate_client
    _redis_client = redis_client

    logger.info("Files router initialized successfully (with Pareto analysis and promotion)")
