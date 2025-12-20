"""Archive extraction tool API (ZIP, 7z, tar, etc.)."""
import asyncio
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(
    title="RAG Tool: Archive Extractor",
    description="Extract archives (ZIP, 7z, tar.gz, tar.xz, etc.) in a secure environment",
    version="1.0.0",
)

# Working directory for extractions
WORK_DIR = Path(os.getenv("WORK_DIR", "/work"))
WORK_DIR.mkdir(parents=True, exist_ok=True)


class ExtractRequest(BaseModel):
    """Request to extract an archive."""
    archive_path: str = Field(..., description="Absolute path to archive file")
    output_dir: Optional[str] = Field(
        None,
        description="Output directory. If not provided, uses WORK_DIR with archive name"
    )
    max_size_mb: Optional[int] = Field(
        500,
        description="Maximum extracted size in MB (safety limit)"
    )


class ExtractResponse(BaseModel):
    """Response from extraction."""
    success: bool
    output_dir: Optional[str] = None
    extracted_files: Optional[List[str]] = None
    file_count: Optional[int] = None
    total_size_mb: Optional[float] = None
    error: Optional[str] = None


class ListRequest(BaseModel):
    """Request to list archive contents without extracting."""
    archive_path: str = Field(..., description="Absolute path to archive file")


class ListResponse(BaseModel):
    """Response from listing archive contents."""
    success: bool
    files: Optional[List[str]] = None
    file_count: Optional[int] = None
    error: Optional[str] = None


@app.get("/healthz")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "tool-archive"}


@app.post("/list", response_model=ListResponse)
async def list_archive(request: ListRequest):
    """List contents of an archive without extracting."""
    archive_path = Path(request.archive_path)

    # Validate input
    if not archive_path.exists():
        raise HTTPException(status_code=404, detail=f"Archive not found: {archive_path}")

    if not archive_path.is_file():
        raise HTTPException(status_code=400, detail=f"Path is not a file: {archive_path}")

    try:
        files = await _list_archive_contents(archive_path)
        return ListResponse(
            success=True,
            files=files,
            file_count=len(files),
        )
    except Exception as e:
        return ListResponse(
            success=False,
            error=str(e),
        )


@app.post("/extract", response_model=ExtractResponse)
async def extract_archive(request: ExtractRequest):
    """Extract an archive to the specified directory.

    Supports:
    - ZIP (.zip)
    - 7-Zip (.7z)
    - tar (.tar, .tar.gz, .tar.xz, .tar.bz2, .tgz)
    - RAR (.rar)
    """
    archive_path = Path(request.archive_path)

    # Validate input
    if not archive_path.exists():
        raise HTTPException(status_code=404, detail=f"Archive not found: {archive_path}")

    if not archive_path.is_file():
        raise HTTPException(status_code=400, detail=f"Path is not a file: {archive_path}")

    # Determine output directory
    if request.output_dir:
        output_dir = Path(request.output_dir)
    else:
        output_name = archive_path.stem
        output_dir = WORK_DIR / output_name

    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Extract based on file extension
        result = await _extract_archive(
            archive_path,
            output_dir,
            max_size_mb=request.max_size_mb
        )

        if result["success"]:
            # Get list of extracted files
            extracted_files = []
            total_size = 0

            for root, _, files in os.walk(output_dir):
                for file in files:
                    file_path = Path(root) / file
                    rel_path = file_path.relative_to(output_dir)
                    extracted_files.append(str(rel_path))
                    total_size += file_path.stat().st_size

            total_size_mb = total_size / (1024 * 1024)

            # Safety check: verify size limit
            if request.max_size_mb and total_size_mb > request.max_size_mb:
                # Clean up
                shutil.rmtree(output_dir)
                return ExtractResponse(
                    success=False,
                    error=f"Extracted size ({total_size_mb:.2f} MB) exceeds limit ({request.max_size_mb} MB)",
                )

            return ExtractResponse(
                success=True,
                output_dir=str(output_dir),
                extracted_files=extracted_files,
                file_count=len(extracted_files),
                total_size_mb=total_size_mb,
            )
        else:
            return ExtractResponse(
                success=False,
                error=result.get("error", "Unknown error during extraction"),
            )

    except Exception as e:
        # Clean up on error
        if output_dir.exists():
            shutil.rmtree(output_dir, ignore_errors=True)

        return ExtractResponse(
            success=False,
            error=str(e),
        )


async def _list_archive_contents(archive_path: Path) -> List[str]:
    """List files in an archive."""
    suffix = archive_path.suffix.lower()

    if suffix == ".zip":
        cmd = ["unzip", "-l", str(archive_path)]
    elif suffix == ".7z":
        cmd = ["7z", "l", str(archive_path)]
    elif suffix in [".tar", ".tgz", ".tar.gz", ".tar.xz", ".tar.bz2"]:
        cmd = ["tar", "-tf", str(archive_path)]
    elif suffix == ".rar":
        cmd = ["unrar", "l", str(archive_path)]
    else:
        raise ValueError(f"Unsupported archive format: {suffix}")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        raise RuntimeError(f"Failed to list archive: {stderr.decode('utf-8', errors='replace')}")

    # Parse output (simplified - just get filenames)
    output = stdout.decode("utf-8", errors="replace")
    files = [line.strip() for line in output.splitlines() if line.strip()]

    return files


async def _extract_archive(archive_path: Path, output_dir: Path, max_size_mb: int) -> dict:
    """Extract archive to output directory."""
    suffix = archive_path.suffix.lower()

    # Build extraction command based on archive type
    if suffix == ".zip":
        cmd = ["unzip", "-q", "-o", str(archive_path), "-d", str(output_dir)]
    elif suffix == ".7z":
        cmd = ["7z", "x", f"-o{output_dir}", "-y", str(archive_path)]
    elif suffix in [".tar", ".tgz", ".tar.gz", ".tar.xz", ".tar.bz2"]:
        cmd = ["tar", "-xf", str(archive_path), "-C", str(output_dir)]
    elif suffix == ".rar":
        cmd = ["unrar", "x", "-o+", str(archive_path), str(output_dir)]
    else:
        return {
            "success": False,
            "error": f"Unsupported archive format: {suffix}",
        }

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        success = proc.returncode == 0

        return {
            "success": success,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "error": None if success else f"Extraction failed with code {proc.returncode}",
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
