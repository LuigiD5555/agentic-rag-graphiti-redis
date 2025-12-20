"""GPU-accelerated processing tool API."""
import asyncio
import os
from pathlib import Path
from typing import Optional, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(
    title="RAG Tool: GPU Accelerator",
    description="GPU-accelerated processing for OCR, image processing, and compute-intensive tasks",
    version="1.0.0",
)

# Working directory
WORK_DIR = Path(os.getenv("WORK_DIR", "/work"))
WORK_DIR.mkdir(parents=True, exist_ok=True)


class GPUInfoResponse(BaseModel):
    """GPU information response."""
    available: bool
    device_count: int
    devices: list


class GPUOCRRequest(BaseModel):
    """Request for GPU-accelerated OCR."""
    input_path: str = Field(..., description="Absolute path to input file")
    language: str = Field(default="eng", description="Language code")
    output_path: Optional[str] = Field(None, description="Output path")


class GPUOCRResponse(BaseModel):
    """Response from GPU OCR."""
    success: bool
    output_path: Optional[str] = None
    text: Optional[str] = None
    processing_time_ms: Optional[float] = None
    error: Optional[str] = None


@app.get("/healthz")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "tool-gpu"}


@app.get("/gpu-info", response_model=GPUInfoResponse)
async def gpu_info():
    """Get GPU information using nvidia-smi."""
    try:
        # Check if NVIDIA GPU is available
        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi",
            "--query-gpu=index,name,memory.total,memory.free",
            "--format=csv,noheader",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode == 0:
            output = stdout.decode("utf-8", errors="replace")
            devices = []

            for line in output.strip().split("\n"):
                if line.strip():
                    parts = [p.strip() for p in line.split(",")]
                    if len(parts) >= 4:
                        devices.append({
                            "index": int(parts[0]),
                            "name": parts[1],
                            "memory_total": parts[2],
                            "memory_free": parts[3],
                        })

            return GPUInfoResponse(
                available=True,
                device_count=len(devices),
                devices=devices,
            )
        else:
            return GPUInfoResponse(
                available=False,
                device_count=0,
                devices=[],
            )

    except FileNotFoundError:
        # nvidia-smi not found
        return GPUInfoResponse(
            available=False,
            device_count=0,
            devices=[],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to query GPU: {str(e)}")


@app.post("/gpu-ocr", response_model=GPUOCRResponse)
async def gpu_ocr(request: GPUOCRRequest):
    """Perform GPU-accelerated OCR using EasyOCR or similar.

    This is a placeholder implementation. In production, you would use:
    - EasyOCR (GPU-accelerated)
    - PaddleOCR (GPU support)
    - Surya OCR
    - Or custom CUDA kernels
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
        output_name = f"{input_path.stem}_gpu_ocr.txt"
        output_path = WORK_DIR / output_name

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        # TODO: Implement actual GPU-accelerated OCR
        # For now, this is a placeholder that falls back to CPU

        import time
        start_time = time.time()

        # Placeholder: simulate OCR processing
        result_text = f"[GPU OCR Placeholder]\nProcessed: {input_path.name}\nLanguage: {request.language}\n"
        result_text += "Note: This is a placeholder. Implement with EasyOCR, PaddleOCR, or similar.\n"

        # Write output
        with output_path.open("w", encoding="utf-8") as f:
            f.write(result_text)

        processing_time = (time.time() - start_time) * 1000  # ms

        return GPUOCRResponse(
            success=True,
            output_path=str(output_path),
            text=result_text,
            processing_time_ms=processing_time,
        )

    except Exception as e:
        return GPUOCRResponse(
            success=False,
            error=str(e),
        )


@app.post("/benchmark")
async def benchmark_gpu():
    """Run a simple GPU benchmark to verify CUDA is working.

    This endpoint can run a simple matrix multiplication or similar
    to verify GPU acceleration is functioning.
    """
    try:
        # Try to import torch and check CUDA
        try:
            import torch
            cuda_available = torch.cuda.is_available()

            if cuda_available:
                device_count = torch.cuda.device_count()
                device_name = torch.cuda.get_device_name(0) if device_count > 0 else "N/A"

                # Simple benchmark: matrix multiplication
                size = 1000
                a = torch.randn(size, size, device="cuda")
                b = torch.randn(size, size, device="cuda")

                import time
                start = time.time()
                c = torch.matmul(a, b)
                torch.cuda.synchronize()
                elapsed = time.time() - start

                return {
                    "cuda_available": True,
                    "device_count": device_count,
                    "device_name": device_name,
                    "benchmark": {
                        "operation": f"{size}x{size} matrix multiplication",
                        "time_ms": elapsed * 1000,
                    }
                }
            else:
                return {
                    "cuda_available": False,
                    "message": "CUDA not available (CPU mode)",
                }

        except ImportError:
            return {
                "cuda_available": False,
                "message": "PyTorch not installed",
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Benchmark failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
