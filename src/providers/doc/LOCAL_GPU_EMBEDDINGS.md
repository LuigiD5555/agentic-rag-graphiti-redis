# Local GPU Embeddings (Optional)

This document explains how to optionally enable local GPU embeddings using `sentence-transformers` instead of LM Studio.

## Default Configuration (LM Studio)

By default, the system uses **LM Studio** for embeddings with **auto-detection of model dimensions**:

- ✅ No torch/sentence-transformers required (~3 GB saved)
- ✅ Automatically detects dimensions from the first available embedding model in LM Studio
- ✅ Lightweight container
- ✅ Works with any LM Studio embedding model (384, 768, 1024, 1536 dims)

```bash
# .env (default configuration)
EMBEDDING_BACKEND=lmstudio
EMBEDDING_DIM=768  # Only used as fallback if auto-detection fails
```

## Enabling Local GPU Embeddings

If you want to run embeddings locally using your GPU/CPU (without LM Studio):

### 1. Install Dependencies

**For local development:**
```bash
pip install -r requirements-local-gpu.txt
```

**For Docker/Podman:**
```bash
# In .env, set:
INSTALL_LOCAL_GPU_DEPS=1

# Rebuild the container
podman-compose build --no-cache app
podman-compose up -d
```

### 2. Configure .env

```bash
# Switch to local GPU embeddings
EMBEDDING_BACKEND=local_gpu
LOCAL_GPU_EMBED_MODEL=sentence-transformers/all-mpnet-base-v2
LOCAL_GPU_DEVICE=cuda  # or 'cpu' or 'auto'
LOCAL_GPU_BATCH_SIZE=32

# EMBEDDING_DIM will be auto-detected from the model
# But you can override it if needed
EMBEDDING_DIM=768
```

### 3. Supported Models

The system automatically detects dimensions for popular models:

| Model | Dimensions |
|-------|------------|
| all-mpnet-base-v2 | 768 |
| all-MiniLM-L6-v2 | 384 |
| all-roberta-large-v1 | 768 |
| bge-base-en-v1.5 | 768 |
| e5-base-v2 | 768 |

See `src/providers/lmstudio/model_manager.py` for the full list.

## Comparison

| Feature | LM Studio (default) | Local GPU |
|---------|---------------------|-----------|
| Container size | ~2 GB | ~5 GB |
| GPU required | No | Optional |
| Model management | Via LM Studio UI | Via HuggingFace |
| Dimension detection | ✅ Automatic | ✅ Automatic |
| Batch support | ✅ | ✅ |
| Offline support | Requires LM Studio | ✅ Full offline |

## Troubleshooting

### "ModuleNotFoundError: No module named 'torch'"

Install local GPU dependencies:
```bash
pip install -r requirements-local-gpu.txt
```

### "CUDA not available"

The system will automatically fall back to CPU. To force CPU mode:
```bash
LOCAL_GPU_DEVICE=cpu
```

### Wrong dimensions detected

Override auto-detection:
```bash
EMBEDDING_DIM=768  # Force specific dimension
```

## Switching Back to LM Studio

```bash
# In .env
EMBEDDING_BACKEND=lmstudio

# Restart container
podman-compose restart app
```

No rebuild needed - the local GPU dependencies remain in the container but are not loaded.
