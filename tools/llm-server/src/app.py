"""LLM Model Server - Lightweight alternative to LM Studio."""
import asyncio
import os
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from huggingface_hub import snapshot_download, hf_hub_download
import httpx

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="RAG Tool: LLM Server",
    description="Lightweight LLM model management and inference server",
    version="1.0.0",
)

# Directories
MODELS_DIR = Path(os.getenv("MODELS_DIR", "/models"))
WORK_DIR = Path(os.getenv("WORK_DIR", "/work"))
MODELS_DIR.mkdir(parents=True, exist_ok=True)
WORK_DIR.mkdir(parents=True, exist_ok=True)

# Supported models configuration
SUPPORTED_MODELS = {
    "liquid-lfm2-2.6b": {
        "name": "LiquidAI LFM2 2.6B",
        "repo_id": "liquidai/LFM-2.6B",
        "type": "text-generation",
        "size_gb": 5.2,
        "description": "Liquid Foundation Model 2.6B - efficient text generation",
    },
    "liquid-lfm2-1.2b": {
        "name": "LiquidAI LFM2 1.2B",
        "repo_id": "liquidai/LFM-1.2B",
        "type": "text-generation",
        "size_gb": 2.4,
        "description": "Liquid Foundation Model 1.2B - compact text generation",
    },
    "whisper-base": {
        "name": "OpenAI Whisper Base",
        "repo_id": "openai/whisper-base",
        "type": "speech-to-text",
        "size_gb": 0.3,
        "description": "Whisper base model for speech recognition",
    },
    "whisper-small": {
        "name": "OpenAI Whisper Small",
        "repo_id": "openai/whisper-small",
        "type": "speech-to-text",
        "size_gb": 0.5,
        "description": "Whisper small model for speech recognition",
    },
    "dolphin-gemma2-2b": {
        "name": "Dolphin 2.9.4 Gemma 2 2B",
        "repo_id": "cognitivecomputations/dolphin-2.9.4-gemma2-2b-gguf",
        "type": "text-generation",
        "size_gb": 1.5,
        "description": "Dolphin fine-tuned Gemma 2 2B (GGUF format)",
        "gguf_file": "dolphin-2.9.4-gemma2-2b-Q4_K_M.gguf",
    },
    "openmath-nemotron-1.5b": {
        "name": "NVIDIA OpenMath Nemotron 1.5B",
        "repo_id": "nvidia/OpenMath2-Llama3.1-8B",
        "type": "math-reasoning",
        "size_gb": 3.0,
        "description": "NVIDIA OpenMath for mathematical reasoning",
    },
}

# Track loaded models
loaded_models: Dict[str, Any] = {}


class ModelInfo(BaseModel):
    """Model information."""
    model_id: str
    name: str
    type: str
    size_gb: float
    description: str
    downloaded: bool
    loaded: bool
    download_path: Optional[str] = None


class ModelListResponse(BaseModel):
    """Response for list models endpoint."""
    models: List[ModelInfo]


class DownloadRequest(BaseModel):
    """Request to download a model."""
    model_id: str = Field(..., description="Model ID from supported models list")


class DownloadResponse(BaseModel):
    """Response from model download."""
    success: bool
    model_id: str
    path: Optional[str] = None
    message: Optional[str] = None
    error: Optional[str] = None


class LoadModelRequest(BaseModel):
    """Request to load a model into memory."""
    model_id: str = Field(..., description="Model ID to load")
    quantization: Optional[str] = Field(None, description="Quantization level (e.g., 'Q4_K_M')")


class LoadModelResponse(BaseModel):
    """Response from load model."""
    success: bool
    model_id: str
    message: Optional[str] = None
    error: Optional[str] = None


class InferenceRequest(BaseModel):
    """Request for model inference."""
    model_id: str = Field(..., description="Model ID to use")
    prompt: str = Field(..., description="Input prompt")
    max_tokens: int = Field(default=512, description="Maximum tokens to generate")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    top_p: float = Field(default=0.9, ge=0.0, le=1.0)


class InferenceResponse(BaseModel):
    """Response from inference."""
    success: bool
    model_id: str
    response: Optional[str] = None
    tokens_generated: Optional[int] = None
    inference_time_ms: Optional[float] = None
    error: Optional[str] = None


@app.get("/healthz")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "tool-llm-server"}


@app.get("/models", response_model=ModelListResponse)
async def list_models():
    """List all supported models and their status."""
    models = []
    for model_id, config in SUPPORTED_MODELS.items():
        # Check if model is downloaded
        model_path = MODELS_DIR / model_id
        downloaded = model_path.exists()

        # Check if model is loaded
        loaded = model_id in loaded_models

        models.append(ModelInfo(
            model_id=model_id,
            name=config["name"],
            type=config["type"],
            size_gb=config["size_gb"],
            description=config["description"],
            downloaded=downloaded,
            loaded=loaded,
            download_path=str(model_path) if downloaded else None,
        ))

    return ModelListResponse(models=models)


@app.post("/models/download", response_model=DownloadResponse)
async def download_model(request: DownloadRequest):
    """Download a model from Hugging Face."""
    model_id = request.model_id

    if model_id not in SUPPORTED_MODELS:
        raise HTTPException(
            status_code=404,
            detail=f"Model '{model_id}' not found in supported models"
        )

    config = SUPPORTED_MODELS[model_id]
    model_path = MODELS_DIR / model_id

    # Check if already downloaded
    if model_path.exists():
        return DownloadResponse(
            success=True,
            model_id=model_id,
            path=str(model_path),
            message=f"Model '{model_id}' already downloaded",
        )

    try:
        logger.info(f"Downloading model '{model_id}' from {config['repo_id']}")

        # Download from Hugging Face
        if "gguf_file" in config:
            # Download specific GGUF file
            downloaded_path = hf_hub_download(
                repo_id=config["repo_id"],
                filename=config["gguf_file"],
                local_dir=model_path,
                local_dir_use_symlinks=False,
            )
        else:
            # Download full repository
            downloaded_path = snapshot_download(
                repo_id=config["repo_id"],
                local_dir=model_path,
                local_dir_use_symlinks=False,
            )

        logger.info(f"Model '{model_id}' downloaded successfully to {model_path}")

        return DownloadResponse(
            success=True,
            model_id=model_id,
            path=str(model_path),
            message=f"Model '{model_id}' downloaded successfully",
        )

    except Exception as e:
        logger.error(f"Failed to download model '{model_id}': {e}")
        return DownloadResponse(
            success=False,
            model_id=model_id,
            error=str(e),
        )


@app.post("/models/load", response_model=LoadModelResponse)
async def load_model(request: LoadModelRequest):
    """Load a model into memory for inference."""
    model_id = request.model_id

    if model_id not in SUPPORTED_MODELS:
        raise HTTPException(
            status_code=404,
            detail=f"Model '{model_id}' not found in supported models"
        )

    config = SUPPORTED_MODELS[model_id]
    model_path = MODELS_DIR / model_id

    # Check if downloaded
    if not model_path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Model '{model_id}' not downloaded. Download it first using /models/download"
        )

    # Check if already loaded
    if model_id in loaded_models:
        return LoadModelResponse(
            success=True,
            model_id=model_id,
            message=f"Model '{model_id}' already loaded",
        )

    try:
        logger.info(f"Loading model '{model_id}' into memory")

        # Load model based on type
        if "gguf" in config.get("gguf_file", "").lower():
            # Load GGUF model with llama-cpp-python
            from llama_cpp import Llama

            gguf_path = model_path / config["gguf_file"]
            model = Llama(
                model_path=str(gguf_path),
                n_ctx=2048,
                n_threads=4,
                verbose=False,
            )
            loaded_models[model_id] = {
                "model": model,
                "type": "gguf",
                "loaded_at": datetime.now().isoformat(),
            }

        elif config["type"] == "speech-to-text":
            # Load Whisper model
            import whisper
            model = whisper.load_model(config["repo_id"].split("/")[-1])
            loaded_models[model_id] = {
                "model": model,
                "type": "whisper",
                "loaded_at": datetime.now().isoformat(),
            }

        else:
            # Load with transformers
            from transformers import AutoModelForCausalLM, AutoTokenizer

            tokenizer = AutoTokenizer.from_pretrained(str(model_path))
            model = AutoModelForCausalLM.from_pretrained(
                str(model_path),
                device_map="auto",
                torch_dtype="auto",
            )
            loaded_models[model_id] = {
                "model": model,
                "tokenizer": tokenizer,
                "type": "transformers",
                "loaded_at": datetime.now().isoformat(),
            }

        logger.info(f"Model '{model_id}' loaded successfully")

        return LoadModelResponse(
            success=True,
            model_id=model_id,
            message=f"Model '{model_id}' loaded successfully",
        )

    except Exception as e:
        logger.error(f"Failed to load model '{model_id}': {e}")
        return LoadModelResponse(
            success=False,
            model_id=model_id,
            error=str(e),
        )


@app.post("/models/unload")
async def unload_model(model_id: str):
    """Unload a model from memory."""
    if model_id not in loaded_models:
        raise HTTPException(
            status_code=404,
            detail=f"Model '{model_id}' is not loaded"
        )

    del loaded_models[model_id]
    logger.info(f"Model '{model_id}' unloaded from memory")

    return {"success": True, "message": f"Model '{model_id}' unloaded"}


@app.post("/inference", response_model=InferenceResponse)
async def run_inference(request: InferenceRequest):
    """Run inference on a loaded model."""
    model_id = request.model_id

    if model_id not in loaded_models:
        raise HTTPException(
            status_code=400,
            detail=f"Model '{model_id}' is not loaded. Load it first using /models/load"
        )

    model_data = loaded_models[model_id]

    try:
        import time
        start_time = time.time()

        if model_data["type"] == "gguf":
            # GGUF inference with llama-cpp
            model = model_data["model"]
            output = model(
                request.prompt,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                top_p=request.top_p,
            )
            response_text = output["choices"][0]["text"]
            tokens_generated = output["usage"]["completion_tokens"]

        elif model_data["type"] == "transformers":
            # Transformers inference
            model = model_data["model"]
            tokenizer = model_data["tokenizer"]

            inputs = tokenizer(request.prompt, return_tensors="pt").to(model.device)
            outputs = model.generate(
                **inputs,
                max_new_tokens=request.max_tokens,
                temperature=request.temperature,
                top_p=request.top_p,
                do_sample=True,
            )
            response_text = tokenizer.decode(outputs[0], skip_special_tokens=True)
            tokens_generated = len(outputs[0]) - len(inputs["input_ids"][0])

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Model type '{model_data['type']}' not supported for text inference"
            )

        inference_time = (time.time() - start_time) * 1000  # ms

        return InferenceResponse(
            success=True,
            model_id=model_id,
            response=response_text,
            tokens_generated=tokens_generated,
            inference_time_ms=inference_time,
        )

    except Exception as e:
        logger.error(f"Inference failed for model '{model_id}': {e}")
        return InferenceResponse(
            success=False,
            model_id=model_id,
            error=str(e),
        )


@app.get("/stats")
async def get_stats():
    """Get server statistics."""
    return {
        "loaded_models": list(loaded_models.keys()),
        "total_models": len(SUPPORTED_MODELS),
        "models_dir": str(MODELS_DIR),
        "work_dir": str(WORK_DIR),
    }


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
