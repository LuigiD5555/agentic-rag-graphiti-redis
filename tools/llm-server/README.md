# LLM Server Tool

Lightweight LLM model management and inference server - a replacement for LM Studio with built-in support for specific models.

## Supported Models

This tool provides easy management for the following models:

### Text Generation Models
- **LiquidAI LFM2 2.6B** - Efficient foundation model (5.2 GB)
- **LiquidAI LFM2 1.2B** - Compact foundation model (2.4 GB)
- **Dolphin 2.9.4 Gemma 2 2B** - Fine-tuned Gemma 2 in GGUF format (1.5 GB)

### Speech-to-Text Models
- **Whisper Base** - Speech recognition (0.3 GB)
- **Whisper Small** - Speech recognition (0.5 GB)

### Math/Reasoning Models
- **NVIDIA OpenMath Nemotron 1.5B** - Mathematical reasoning (3.0 GB)

## API Endpoints

### Health Check
```bash
GET /healthz
```

### List Models
```bash
GET /models
```
Returns list of all supported models with their download and load status.

### Download Model
```bash
POST /models/download
{
  "model_id": "liquid-lfm2-1.2b"
}
```

### Load Model
```bash
POST /models/load
{
  "model_id": "liquid-lfm2-1.2b",
  "quantization": "Q4_K_M"  # optional for GGUF models
}
```

### Run Inference
```bash
POST /inference
{
  "model_id": "liquid-lfm2-1.2b",
  "prompt": "What is the capital of France?",
  "max_tokens": 512,
  "temperature": 0.7,
  "top_p": 0.9
}
```

### Unload Model
```bash
POST /models/unload?model_id=liquid-lfm2-1.2b
```

### Get Stats
```bash
GET /stats
```

## Usage

### Building the Container
```bash
podman build -t localhost/rag-tool-llm:latest tools/llm-server/
```

### Running with Systemd
```bash
systemctl --user enable --now tool-llm.socket
```

### Manual Run
```bash
podman run --rm \
  --name tool-llm \
  --network rag-network \
  -v llm-models:/models:Z \
  -v rag-work:/work:Z \
  -p 9104:8000 \
  localhost/rag-tool-llm:latest
```

## Model Storage

Models are downloaded to the `/models` volume and persist across container restarts. Each model is stored in its own subdirectory.

## Memory Requirements

- Minimum: 4 GB RAM
- Recommended: 8 GB RAM (allows loading 2-3 small models simultaneously)
- For larger models or multiple loaded models: 16 GB RAM

## Why This Instead of LM Studio?

- **Lightweight**: No GUI overhead, API-only
- **Scriptable**: Easy to automate and integrate
- **Containerized**: Isolated environment with reproducible builds
- **Specific**: Pre-configured with exactly the models you need
- **Resource Efficient**: Lower memory footprint when models aren't loaded
