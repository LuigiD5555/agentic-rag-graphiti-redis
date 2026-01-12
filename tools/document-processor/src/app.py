"""Consolidated Document Processing Tool API (OCR + Office Conversion)."""
import asyncio
import os
import tempfile
from pathlib import Path
from typing import Optional, List, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import pandas as pd

# Initialize application with all improvements
from .init_app import initialize_application

# Initialize on module import
initialize_application()

app = FastAPI(
    title="RAG Tool: Document Processor",
    description="Unified OCR and Office document conversion service",
    version="2.0.0",
)

# Working directory
WORK_DIR = Path(os.getenv("WORK_DIR", "/work"))
WORK_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================================
# OCR Models (from tool-ocr)
# ============================================================================

class OCRRequest(BaseModel):
    """Request to perform OCR on an image or PDF."""
    input_path: str = Field(..., description="Absolute path to input file (image or PDF)")
    language: str = Field(
        default="eng",
        description="Tesseract language code (eng, spa, fra, deu, etc.)"
    )
    output_path: Optional[str] = Field(
        None,
        description="Output text file path. If not provided, uses WORK_DIR"
    )
    psm: int = Field(
        default=3,
        description="Page segmentation mode (0-13). 3=auto, 6=single block"
    )
    output_format: Literal["txt", "hocr", "pdf"] = Field(
        default="txt",
        description="Output format: txt, hocr (HTML), or pdf (searchable PDF)"
    )


class OCRResponse(BaseModel):
    """Response from OCR operation."""
    success: bool
    output_path: Optional[str] = None
    text: Optional[str] = None
    error: Optional[str] = None
    confidence: Optional[float] = None


class PDFToImagesRequest(BaseModel):
    """Request to convert PDF pages to images for OCR."""
    pdf_path: str = Field(..., description="Absolute path to PDF file")
    output_dir: Optional[str] = Field(
        None,
        description="Output directory for images. If not provided, uses WORK_DIR"
    )
    dpi: int = Field(default=300, description="DPI for image conversion")
    format: Literal["png", "jpg"] = Field(default="png", description="Image format")


class PDFToImagesResponse(BaseModel):
    """Response from PDF to images conversion."""
    success: bool
    output_dir: Optional[str] = None
    image_paths: Optional[List[str]] = None
    page_count: Optional[int] = None
    error: Optional[str] = None


# ============================================================================
# Office Conversion Models (from tool-document-processor)
# ============================================================================

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


# ============================================================================
# Health Check Endpoint
# ============================================================================

@app.get("/healthz")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "tool-document-processor", "features": ["ocr", "office"]}


# ============================================================================
# OCR Endpoints (from tool-ocr)
# ============================================================================

@app.post("/ocr", response_model=OCRResponse)
async def perform_ocr(request: OCRRequest):
    """Perform OCR on an image or PDF.

    Supports:
    - Images: PNG, JPG, TIFF, BMP
    - PDF: single or multi-page (will OCR all pages)
    """
    input_path = Path(request.input_path)

    # Validate input
    if not input_path.exists():
        raise HTTPException(status_code=404, detail=f"Input file not found: {input_path}")

    if not input_path.is_file():
        raise HTTPException(status_code=400, detail=f"Path is not a file: {input_path}")

    # Determine output path
    if request.output_path:
        output_path = Path(request.output_path)
    else:
        output_name = f"{input_path.stem}_ocr.{request.output_format}"
        output_path = WORK_DIR / output_name

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not os.access(output_path.parent, os.W_OK):
        return ConvertResponse(
            success=False,
            error=(
                "Output directory is not writable for conversion. "
                f"Directory: {output_path.parent}. WORK_DIR={WORK_DIR}. "
                f"Input file: {input_path}"
            ),
        )

    try:
        result = await _run_tesseract(
            input_path,
            output_path,
            language=request.language,
            psm=request.psm,
            output_format=request.output_format,
        )

        if result["success"]:
            # Read output text if format is txt
            text_content = None
            if request.output_format == "txt" and output_path.exists():
                with output_path.open("r", encoding="utf-8") as f:
                    text_content = f.read()

            return OCRResponse(
                success=True,
                output_path=str(output_path),
                text=text_content,
                confidence=result.get("confidence"),
            )
        else:
            return OCRResponse(
                success=False,
                error=result.get("error", "OCR failed"),
            )

    except Exception as e:
        return OCRResponse(
            success=False,
            error=str(e),
        )


@app.post("/pdf-to-images", response_model=PDFToImagesResponse)
async def pdf_to_images(request: PDFToImagesRequest):
    """Convert PDF pages to images for OCR processing.

    Useful for multi-page PDFs or when you need more control over image preprocessing.
    """
    pdf_path = Path(request.pdf_path)

    # Validate input
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail=f"PDF not found: {pdf_path}")

    if not pdf_path.is_file():
        raise HTTPException(status_code=400, detail=f"Path is not a file: {pdf_path}")

    # Determine output directory
    if request.output_dir:
        output_dir = Path(request.output_dir)
    else:
        output_name = f"{pdf_path.stem}_pages"
        output_dir = WORK_DIR / output_name

    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = await _pdf_to_images(
            pdf_path,
            output_dir,
            dpi=request.dpi,
            img_format=request.format,
        )

        if result["success"]:
            return PDFToImagesResponse(
                success=True,
                output_dir=str(output_dir),
                image_paths=result.get("image_paths", []),
                page_count=result.get("page_count", 0),
            )
        else:
            return PDFToImagesResponse(
                success=False,
                error=result.get("error", "PDF conversion failed"),
            )

    except Exception as e:
        return PDFToImagesResponse(
            success=False,
            error=str(e),
        )


# ============================================================================
# Office Conversion Endpoint (from tool-document-processor)
# ============================================================================

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
            # Convert to plain text using extension-aware strategy
            result = await _convert_to_text_with_strategy(input_path, output_path)
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


# ============================================================================
# OCR Helper Functions
# ============================================================================

async def _run_tesseract(
    input_path: Path,
    output_path: Path,
    language: str,
    psm: int,
    output_format: str,
) -> dict:
    """Run Tesseract OCR."""
    # Tesseract adds extension automatically, so we need to strip it from output path
    output_base = output_path.with_suffix("")

    # Build command
    cmd = [
        "tesseract",
        str(input_path),
        str(output_base),
        "-l", language,
        "--psm", str(psm),
    ]

    # Add output format
    if output_format == "txt":
        cmd.append("txt")
    elif output_format == "hocr":
        cmd.append("hocr")
    elif output_format == "pdf":
        cmd.append("pdf")

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
            "error": None if success else f"Tesseract exited with code {proc.returncode}",
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


async def _pdf_to_images(
    pdf_path: Path,
    output_dir: Path,
    dpi: int,
    img_format: str,
) -> dict:
    """Convert PDF to images using pdftoppm (from poppler-utils)."""
    output_prefix = output_dir / pdf_path.stem

    # pdftoppm command
    # -<format>: output format (png, jpeg)
    # -r: resolution (DPI)
    format_flag = "-png" if img_format == "png" else "-jpeg"

    cmd = [
        "pdftoppm",
        format_flag,
        "-r", str(dpi),
        str(pdf_path),
        str(output_prefix),
    ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        success = proc.returncode == 0

        if success:
            # List generated images
            ext = ".png" if img_format == "png" else ".jpg"
            image_paths = sorted([
                str(p) for p in output_dir.glob(f"{pdf_path.stem}-*{ext}")
            ])

            return {
                "success": True,
                "image_paths": image_paths,
                "page_count": len(image_paths),
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
            }
        else:
            return {
                "success": False,
                "error": f"pdftoppm exited with code {proc.returncode}",
                "stdout": stdout.decode("utf-8", errors="replace"),
                "stderr": stderr.decode("utf-8", errors="replace"),
            }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


# ============================================================================
# Office Conversion Helper Functions
# ============================================================================

def _libreoffice_error_message(return_code: int, input_path: Path) -> str:
    if return_code == 1:
        return (
            "LibreOffice exit code 1: General error. File may be corrupted, encrypted, "
            f"or unsupported. File: {input_path}"
        )
    if return_code == 5:
        return f"LibreOffice exit code 5: Memory allocation failure. File may be too large: {input_path}"
    if return_code == 6:
        return f"LibreOffice exit code 6: I/O error. Check file permissions: {input_path}"
    if return_code == 137:
        return (
            "LibreOffice exit code 137: Process killed (likely OOM). "
            f"Try increasing memory limits. File: {input_path}"
        )
    return f"LibreOffice exited with code {return_code}. File: {input_path}"


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

        stdout_str = stdout.decode("utf-8", errors="replace")
        stderr_str = stderr.decode("utf-8", errors="replace")
        
        # LibreOffice outputs to <input_stem>.pdf by default
        generated_pdf = output_path.parent / f"{input_path.stem}.pdf"

        if generated_pdf.exists() and generated_pdf != output_path:
            generated_pdf.rename(output_path)

        success = proc.returncode == 0 and output_path.exists()

        if not success:
            error_msg = _libreoffice_error_message(proc.returncode, input_path)
            return {
                "success": False,
                "stdout": stdout_str,
                "stderr": stderr_str,
                "error": f"PDF conversion failed. {error_msg}",
            }

        return {
            "success": True,
            "stdout": stdout_str,
            "stderr": stderr_str,
            "error": None,
        }

    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": "",
            "error": f"Unexpected error in _convert_to_pdf: {str(e)}",
        }

SPREADSHEET_EXTENSIONS = {".csv", ".xls", ".xlsx", ".xlsm"}
WRITER_EXTENSIONS = {".doc", ".docx", ".odt", ".rtf"}
SLIDE_EXTENSIONS = {".ppt", ".pptx", ".odp"}


async def _convert_to_text_with_strategy(input_path: Path, output_path: Path) -> dict:
    """Select the best text extraction path based on file type."""
    suffix = input_path.suffix.lower()

    if suffix in SPREADSHEET_EXTENSIONS:
        sheet_result = await _convert_spreadsheet_to_text(input_path, output_path)
        if sheet_result["success"]:
            return sheet_result

        fallback_result = await _convert_to_text(input_path, output_path)
        if fallback_result["success"]:
            return fallback_result

        sheet_error = sheet_result.get("error") or "Unknown error"
        fallback_error = fallback_result.get("error") or "Unknown error"
        return {
            "success": False,
            "stdout": fallback_result.get("stdout", ""),
            "stderr": fallback_result.get("stderr", ""),
            "error": (
                f"Text extraction failed for spreadsheet {input_path}. "
                "Attempt 1 (pandas CSV export) failed: "
                f"{sheet_error}. "
                "Attempt 2 (LibreOffice -> PDF -> pdftotext) failed: "
                f"{fallback_error}. "
                "If both failed, the file is likely corrupted, encrypted, or uses an unsupported format."
            ),
        }

    if suffix in WRITER_EXTENSIONS or suffix in SLIDE_EXTENSIONS:
        direct_result = await _convert_to_text_direct_libreoffice(input_path, output_path)
        if direct_result["success"]:
            return direct_result

        fallback_result = await _convert_to_text(input_path, output_path)
        if fallback_result["success"]:
            return fallback_result

        direct_error = direct_result.get("error") or "Unknown error"
        fallback_error = fallback_result.get("error") or "Unknown error"
        return {
            "success": False,
            "stdout": fallback_result.get("stdout", ""),
            "stderr": fallback_result.get("stderr", ""),
            "error": (
                f"Text extraction failed for {input_path}. "
                "Attempt 1 (LibreOffice direct text export) failed: "
                f"{direct_error}. "
                "Attempt 2 (LibreOffice -> PDF -> pdftotext) failed: "
                f"{fallback_error}. "
                "If both failed, the file is likely corrupted, encrypted, or uses an unsupported format."
            ),
        }

    # Fallback: PDF + pdftotext path
    return await _convert_to_text(input_path, output_path)


async def _convert_to_text_direct_libreoffice(input_path: Path, output_path: Path) -> dict:
    """Convert document to text using LibreOffice's direct export."""
    cmd = [
        "libreoffice",
        "--headless",
        "--convert-to", "txt:Text",
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

        generated_txt = output_path.parent / f"{input_path.stem}.txt"
        if generated_txt.exists() and generated_txt != output_path:
            if output_path.exists():
                output_path.unlink()
            generated_txt.rename(output_path)

        success = proc.returncode == 0 and output_path.exists() and output_path.stat().st_size > 0

        error_msg = None
        if not success:
            error_msg = _libreoffice_error_message(proc.returncode, input_path)
            error_msg = f"LibreOffice direct text export failed. {error_msg}"

        return {
            "success": success,
            "stdout": stdout.decode("utf-8", errors="replace"),
            "stderr": stderr.decode("utf-8", errors="replace"),
            "error": error_msg,
        }

    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


async def _convert_spreadsheet_to_text(input_path: Path, output_path: Path) -> dict:
    """Convert spreadsheet formats to text using pandas."""
    try:
        if not os.access(output_path.parent, os.W_OK):
            raise PermissionError(
                f"Output directory not writable: {output_path.parent}. WORK_DIR={WORK_DIR}"
            )
        await asyncio.to_thread(_spreadsheet_to_text_sync, input_path, output_path)
        success = output_path.exists() and output_path.stat().st_size > 0
        return {
            "success": success,
            "stdout": "",
            "stderr": "",
            "error": None if success else "Spreadsheet export produced empty output",
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Spreadsheet export failed: {str(e)}",
        }


def _spreadsheet_to_text_sync(input_path: Path, output_path: Path) -> None:
    suffix = input_path.suffix.lower()

    if suffix == ".csv":
        sheets = {"Sheet1": pd.read_csv(input_path, dtype=str, keep_default_na=False)}
    else:
        engine = "openpyxl"
        if suffix == ".xls":
            engine = "xlrd"
        sheets = pd.read_excel(
            input_path,
            sheet_name=None,
            dtype=str,
            engine=engine,
        )

    with output_path.open("w", encoding="utf-8") as handle:
        for sheet_name, frame in sheets.items():
            if len(sheets) > 1:
                handle.write(f"## {sheet_name}\n")
            handle.write(frame.to_csv(index=False))
            handle.write("\n")

async def _convert_to_text(input_path: Path, output_path: Path) -> dict:
    """Convert document to plain text.

    Strategy:
    1. Convert to PDF first (intermediate)
    2. Extract text from PDF using pdftotext
    
    Improved error handling for pdftotext exit code 2 (file not found/permission error)
    """
    # Create temp PDF
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp_pdf = Path(tmp.name)

    try:
        # Step 1: to PDF
        pdf_result = await _convert_to_pdf(input_path, tmp_pdf)
        if not pdf_result["success"]:
            return pdf_result

        # Verify temp PDF exists and is readable
        if not tmp_pdf.exists():
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "error": f"Temporary PDF file not created: {tmp_pdf}",
            }
        
        if tmp_pdf.stat().st_size == 0:
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "error": f"Temporary PDF file is empty: {tmp_pdf}",
            }

        # Step 2: PDF to text
        cmd = ["pdftotext", "-layout", str(tmp_pdf), str(output_path)]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        stdout_str = stdout.decode("utf-8", errors="replace")
        stderr_str = stderr.decode("utf-8", errors="replace")
        
        success = proc.returncode == 0 and output_path.exists()

        if not success:
            # Provide more detailed error messages for common exit codes
            if proc.returncode == 2:
                error_msg = (
                    "pdftotext exit code 2: File not found or permission error. "
                    f"Temp PDF: {tmp_pdf.exists()}, size: "
                    f"{tmp_pdf.stat().st_size if tmp_pdf.exists() else 0} bytes. "
                    f"Output path: {output_path}"
                )
            else:
                error_msg = f"pdftotext exited with code {proc.returncode}. Output path: {output_path}"
            
            return {
                "success": False,
                "stdout": stdout_str,
                "stderr": stderr_str,
                "error": error_msg,
            }

        return {
            "success": True,
            "stdout": stdout_str,
            "stderr": stderr_str,
            "error": None,
        }

    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": "",
            "error": f"Unexpected error in _convert_to_text: {str(e)}",
        }
    finally:
        # Clean up temp PDF
        if tmp_pdf.exists():
            try:
                tmp_pdf.unlink()
            except:
                pass


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
