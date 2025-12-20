"""OCR tool API using Tesseract."""
import asyncio
import os
from pathlib import Path
from typing import Optional, List, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(
    title="RAG Tool: OCR",
    description="Optical Character Recognition using Tesseract",
    version="1.0.0",
)

# Working directory
WORK_DIR = Path(os.getenv("WORK_DIR", "/work"))
WORK_DIR.mkdir(parents=True, exist_ok=True)


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


@app.get("/healthz")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "tool-ocr"}


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


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
