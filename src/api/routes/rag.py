"""Router for RAG-specific endpoints."""
from pathlib import Path
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Header

from src.api.models_ollama import (
    RagQueryRequest,
    RagQueryResponse,
    RagIngestRequest,
    RagIngestResponse,
    RagToolRequest,
    RagToolResponse,
    RagFileLocationResponse,
    RagFileMetadataResponse,
    AnswerModesPayload,
    AnswerModesResponse,
    AnswerModeConfig,
)
from src.conf import settings
from src.workflows.ingestion.orchestrator import IngestionOrchestrator
from src.workflows.ingestion.options import IngestionOptions
from src.workflows.ingestion.preprocessor import get_preprocessor
from src.workflows.query.pipeline.rag_orchestrator import RAGOrchestrator
from src.middleware.thread_manager import get_thread_id
from src.workflows.query.answer_modes import (
    get_answer_modes,
    update_answer_modes,
    get_answer_mode,
    upsert_answer_mode,
    delete_answer_mode,
)
from src.utils.structured_log import emit_structured_log
from src import logger

router = APIRouter(prefix="/rag", tags=["rag"])


async def get_rag_orchestrator() -> RAGOrchestrator:
    """Dependency injection for RAG orchestrator."""
    raise HTTPException(status_code=500, detail="RAG orchestrator not initialized")


async def get_ingestion_orchestrator() -> IngestionOrchestrator:
    """Dependency injection for ingestion orchestrator."""
    raise HTTPException(status_code=500, detail="Ingestion orchestrator not initialized")


@router.post("/query", response_model=RagQueryResponse)
async def rag_query(
    request: RagQueryRequest,
    rag: RAGOrchestrator = Depends(get_rag_orchestrator),
    thread_id: str = Depends(get_thread_id),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
) -> RagQueryResponse:
    request_id = x_request_id or f"api-query-{uuid.uuid4().hex[:12]}"
    # Use default values with early assignment
    temperature = request.temperature or settings.RAG_DEFAULT_TEMPERATURE
    max_tokens = request.max_tokens or settings.RAG_DEFAULT_MAX_TOKENS
    emit_structured_log(
        logger,
        component="api_rag_query",
        request_id=request_id,
        operation="query_endpoint_start",
        model_name="",
        query_chars=len(request.query),
    )
    result = rag.query(
        question=request.query,
        top_k=request.top_k,
        filters=request.filters,
        temperature=temperature,
        max_tokens=max_tokens,
        system_prompt=request.system,
        session_id=thread_id,
        request_id=request_id,
    )
    emit_structured_log(
        logger,
        component="api_rag_query",
        request_id=request_id,
        operation="query_endpoint_end",
        model_name=result.get("metadata", {}).get("model", "") or "",
        retrieved_count=result.get("metadata", {}).get("retrieved_count", 0),
    )
    sources = result.get("sources", []) if request.include_sources else []
    metadata = result.get("metadata", {})
    metadata["request_id"] = request_id
    return RagQueryResponse(
        answer=result["answer"],
        sources=sources,
        metadata=metadata,
    )


@router.get("/answer-modes", response_model=AnswerModesResponse)
async def list_answer_modes() -> AnswerModesResponse:
    modes = get_answer_modes()
    return AnswerModesResponse(
        default_mode=modes.get("default_mode", "detailed"),
        modes=modes.get("modes", {}),
    )


@router.put("/answer-modes", response_model=AnswerModesResponse)
async def put_answer_modes(payload: AnswerModesPayload) -> AnswerModesResponse:
    data = payload.model_dump(exclude_none=True)
    merge = data.pop("merge", True)
    try:
        updated = update_answer_modes(payload=data, merge=bool(merge))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AnswerModesResponse(
        default_mode=updated.get("default_mode", "detailed"),
        modes=updated.get("modes", {}),
    )


@router.get("/answer-modes/{mode_name}", response_model=AnswerModeConfig)
async def get_answer_mode_by_name(mode_name: str) -> AnswerModeConfig:
    mode = get_answer_mode(mode_name)
    if mode is None:
        raise HTTPException(status_code=404, detail="Answer mode not found.")
    return AnswerModeConfig.model_validate(mode)


@router.put("/answer-modes/{mode_name}", response_model=AnswerModeConfig)
async def put_answer_mode_by_name(
    mode_name: str,
    payload: AnswerModeConfig,
    merge: bool = True,
) -> AnswerModeConfig:
    try:
        updated = upsert_answer_mode(
            mode_name=mode_name,
            config=payload.model_dump(exclude_none=True),
            merge=merge,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AnswerModeConfig.model_validate(updated)


@router.delete("/answer-modes/{mode_name}", response_model=AnswerModesResponse)
async def delete_answer_mode_by_name(mode_name: str) -> AnswerModesResponse:
    try:
        updated = delete_answer_mode(mode_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return AnswerModesResponse(
        default_mode=updated.get("default_mode", "detailed"),
        modes=updated.get("modes", {}),
    )


@router.post("/ingest", response_model=RagIngestResponse)
async def rag_ingest(
    request: RagIngestRequest,
    ingestion: IngestionOrchestrator = Depends(get_ingestion_orchestrator),
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
) -> RagIngestResponse:
    request_id = x_request_id or f"api-ingest-{uuid.uuid4().hex[:12]}"
    endpoint_start = time.perf_counter()
    emit_structured_log(
        logger,
        component="api_rag_ingest",
        request_id=request_id,
        operation="ingest_endpoint_start",
        model_name="",
        path_count=len(request.paths),
    )
    # Use default values with early assignment
    enabled_paths = tuple(request.enabled_paths or ())
    allowed_extensions = set(request.allowed_extensions or ())
    excluded_dirs = set(request.excluded_dirs or ())
    excluded_globs = set(request.excluded_globs or ())
    max_files = int(request.max_files or 0)
    scan_progress_every = int(request.scan_progress_every or 0)
    stream_ingest = bool(request.streaming) if request.streaming is not None else True
    
    options = IngestionOptions(
        root_paths=tuple(request.paths),
        enabled_paths=enabled_paths,
        allowed_extensions=allowed_extensions,
        excluded_directory_names=excluded_dirs,
        excluded_path_globs=excluded_globs,
        follow_symbolic_links=bool(request.follow_symlinks),
        dry_run=bool(request.dry_run),
        per_file_mode=bool(request.per_file),
        maximum_files=max_files,
        stream_ingest=stream_ingest,
        scan_progress_every=scan_progress_every,
        strategy=request.strategy,
        phased_ingestion=request.phased_ingestion,
        max_ram_usage_percent=request.max_ram_percent,
        run_id=request.run_id,
    )
    emit_structured_log(
        logger,
        component="api_rag_ingest",
        request_id=request_id,
        operation="ingest_endpoint_heavy_start",
        model_name="",
        run_id=options.run_id,
    )
    report = ingestion.run_with_report(options)
    emit_structured_log(
        logger,
        component="api_rag_ingest",
        request_id=request_id,
        operation="ingest_endpoint_end",
        model_name="",
        duration_ms=(time.perf_counter() - endpoint_start) * 1000.0,
        status=report.get("status"),
        run_id=report.get("run_id"),
    )
    pipeline_report = report.get("pipeline", {})
    return RagIngestResponse(
        status=report["status"],
        ingested=pipeline_report.get("ingested", 0),
        failed=pipeline_report.get("failed", 0),
        candidates=pipeline_report.get("candidates"),
        run_id=report.get("run_id"),
        strategy=report.get("strategy"),
    )


@router.post("/tools/zip", response_model=RagToolResponse)
async def tool_zip(request: RagToolRequest) -> RagToolResponse:
    preprocessor = get_preprocessor()
    output = preprocessor.extract_archive(Path(request.input_path))
    if output is None:
        return RagToolResponse(success=False, error="Archive extraction failed.")
    return RagToolResponse(
        success=True,
        output_dir=str(output),
    )


@router.post("/tools/office", response_model=RagToolResponse)
async def tool_office(request: RagToolRequest) -> RagToolResponse:
    preprocessor = get_preprocessor()
    output = preprocessor.convert_office_document(Path(request.input_path))
    if output is None:
        return RagToolResponse(success=False, error="Office conversion failed.")
    return RagToolResponse(
        success=True,
        output_path=str(output),
    )


@router.post("/tools/ocr", response_model=RagToolResponse)
async def tool_ocr(request: RagToolRequest) -> RagToolResponse:
    preprocessor = get_preprocessor()
    output = preprocessor.perform_ocr(Path(request.input_path))
    if output is None:
        return RagToolResponse(success=False, error="OCR failed.")
    return RagToolResponse(
        success=True,
        output_path=str(output),
    )


@router.get("/files/{file_id}/location", response_model=RagFileLocationResponse)
async def file_location(
    file_id: str,
    rag: RAGOrchestrator = Depends(get_rag_orchestrator),
) -> RagFileLocationResponse:
    path = rag.retriever.get_file_location(file_id)
    return RagFileLocationResponse(file_id=file_id, path=path)


@router.get("/files/{file_id}/metadata", response_model=RagFileMetadataResponse)
async def file_metadata(
    file_id: str,
    rag: RAGOrchestrator = Depends(get_rag_orchestrator),
) -> RagFileMetadataResponse:
    metadata = rag.retriever.get_file_metadata(file_id)
    return RagFileMetadataResponse(file_id=file_id, metadata=metadata)
