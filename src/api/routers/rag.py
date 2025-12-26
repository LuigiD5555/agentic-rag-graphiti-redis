"""Router for RAG-specific endpoints."""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from src.api.models_ollama import (
    RagQueryRequest,
    RagQueryResponse,
    RagIngestRequest,
    RagIngestResponse,
    RagToolRequest,
    RagToolResponse,
    RagFileLocationResponse,
    RagFileMetadataResponse,
)
from src.ingestion.orchestrator import IngestionOrchestrator
from src.ingestion.options import IngestionOptions
from src.ingestion.preprocessor import get_preprocessor
from src.rag.pipeline.rag_orchestrator import RAGOrchestrator

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
) -> RagQueryResponse:
    result = rag.query(
        question=request.query,
        top_k=request.top_k,
        filters=request.filters,
        temperature=request.temperature if request.temperature is not None else 0.7,
        max_tokens=request.max_tokens if request.max_tokens is not None else 1024,
        system_prompt=request.system,
    )
    sources = result.get("sources", []) if request.include_sources else []
    return RagQueryResponse(
        answer=result["answer"],
        sources=sources,
        metadata=result.get("metadata", {}),
    )


@router.post("/ingest", response_model=RagIngestResponse)
async def rag_ingest(
    request: RagIngestRequest,
    ingestion: IngestionOrchestrator = Depends(get_ingestion_orchestrator),
) -> RagIngestResponse:
    options = IngestionOptions(
        root_paths=tuple(request.paths),
        enabled_paths=tuple(request.enabled_paths or ()),
        allowed_extensions=set(request.allowed_extensions or ()),
        excluded_directory_names=set(request.excluded_dirs or ()),
        excluded_path_globs=set(request.excluded_globs or ()),
        follow_symbolic_links=bool(request.follow_symlinks),
        dry_run=bool(request.dry_run),
        per_file_mode=bool(request.per_file),
        maximum_files=int(request.max_files or 0),
        stream_ingest=(
            bool(request.streaming)
            if request.streaming is not None
            else True
        ),
        scan_progress_every=int(request.scan_progress_every or 0),
    )
    report = ingestion.run_with_report(options)
    return RagIngestResponse(
        status=report["status"],
        ingested=report["ingested"],
        failed=report["failed"],
        candidates=report.get("candidates"),
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
