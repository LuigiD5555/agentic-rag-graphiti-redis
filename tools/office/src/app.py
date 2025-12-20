"""LibreOffice headless conversion tool API."""
import asyncio
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Literal

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

app = FastAPI(
    title="RAG Tool: Office Converter",
    description="Convert Office documents (DOCX/XLSX/PPTX) to PDF or text",
    version="1.0.0",
)

# Working directory for conversions
WORK_DIR = Path(os.getenv("WORK_DIR", "/work"))
WORK_DIR.mkdir(parents=True, exist_ok=True)


class ConvertRequest(BaseModel):
    """Request to convert a document."""
    input_path: str = Field(..., description="Absolute path to input file")
    output_format: Literal["pdf", "txt", "md"] = Field(
        default="pdf",
        description="Output format: pdf, txt (plain text), or md (markdown)"
    )
    output_path: Optional[str] = Field(
        None,
        description="Optional output path. If not provided, uses WORK_DIR with generated name"
    )


class ConvertResponse(BaseModel):
    """Response from conversion."""
    success: bool
    output_path: Optional[str] = None
    error: Optional[str] = None
    stdout: Optional[str] = None
    stderr: Optional[str] = None


@app.get("/healthz")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "tool-office"}


@app.post("/convert", response_model=ConvertResponse)
async def convert_document(request: ConvertRequest):
    """Convert an Office document to the specified format.

    Supports:
    - DOCX, DOC -> PDF, TXT, MD
    - XLSX, XLS -> PDF, TXT (CSV-like)
    - PPTX, PPT -> PDF
    """
    input_path = Path(request.input_path)

    # Validate input exists and is readable
    if not input_path.exists():
        raise HTTPException(status_code=404, detail=f"Input file not found: {input_path}")

    if not input_path.is_file():
        raise HTTPException(status_code=400, detail=f"Input path is not a file: {input_path}")

    # Determine output path
    if request.output_path:
        output_path = Path(request.output_path)
    else:
        output_name = f"{input_path.stem}.{request.output_format}"
        output_path = WORK_DIR / output_name

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        if request.output_format == "pdf":
            # Convert to PDF using LibreOffice
            result = await _convert_to_pdf(input_path, output_path)
        elif request.output_format == "txt":
            # Convert to plain text
            result = await _convert_to_text(input_path, output_path)
        elif request.output_format == "md":
            # Convert to markdown (simplified)
            result = await _convert_to_markdown(input_path, output_path)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported format: {request.output_format}")

        return ConvertResponse(
            success=result["success"],
            output_path=str(output_path) if result["success"] else None,
            error=result.get("error"),
            stdout=result.get("stdout"),
            stderr=result.get("stderr"),
        )

    except Exception as e:
        return ConvertResponse(
            success=False,
            error=str(e),
        )


async def _convert_to_pdf(input_path: Path, output_path: Path) -> dict:
    """Convert document to PDF using LibreOffice headless."""
    # LibreOffice command:
    # --headless: run without GUI
    # --convert-to pdf: output format
    # --outdir: output directory
    cmd = [
        "libreoffice",
        "--headless",
        "--convert-to", "pdf",
        "--outdir", str(output_path.parent),
        str(input_path),
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        # LibreOffice outputs to <input_stem>.pdf by default
        generated_pdf = output_path.parent / f"{input_path.stem}.pdf"

        if generated_pdf.exists() and generated_pdf != output_path:
            generated_pdf.rename(output_path)

        success = proc.returncode == 0 and output_path.exists()

        return {
            "success": success,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "error": None if success else f"LibreOffice exited with code {proc.returncode}",
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


async def _convert_to_text(input_path: Path, output_path: Path) -> dict:
    """Convert document to plain text.

    Strategy:
    1. Convert to PDF first (intermediate)
    2. Extract text from PDF using pdftotext
    """
    # Create temp PDF
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_pdf = Path(tmp.name)

    try:
        # Step 1: to PDF
        pdf_result = await _convert_to_pdf(input_path, tmp_pdf)
        if not pdf_result["success"]:
            return pdf_result

        # Step 2: PDF to text
        cmd = ["pdftotext", "-layout", str(tmp_pdf), str(output_path)]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        success = proc.returncode == 0 and output_path.exists()

        return {
            "success": success,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "error": None if success else f"pdftotext exited with code {proc.returncode}",
        }

    finally:
        # Clean up temp PDF
        if tmp_pdf.exists():
            tmp_pdf.unlink()


async def _convert_to_markdown(input_path: Path, output_path: Path) -> dict:
    """Convert document to markdown (simplified).

    This is a basic implementation. For now, we extract text and format minimally.
    A more sophisticated approach would use pandoc or similar.
    """
    # For simplicity: convert to text, then add basic markdown structure
    txt_result = await _convert_to_text(input_path, output_path)

    if txt_result["success"]:
        # Add basic markdown header
        with output_path.open("r") as f:
            content = f.read()

        with output_path.open("w") as f:
            f.write(f"# {input_path.stem}\n\n")
            f.write(content)

    return txt_result


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
