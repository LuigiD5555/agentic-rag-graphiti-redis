# Providers Architecture

This document describes the provider system architecture in the RAG project.

## Overview

The provider system implements an adapter pattern to support multiple LLM and embedding providers with a unified interface. This allows the application to seamlessly switch between different backends (OpenAI, Ollama, LM Studio, HuggingFace, etc.) without changing business logic.

## Core Concepts

### Provider Adapter Interface

All providers implement the `ProviderAdapterInterface` defined in [src/providers/adapters/base.py](../adapters/base.py). This interface defines:

- **Chat completion methods**: For conversational interactions
- **Embedding methods**: For text vectorization
- **Model management**: For listing and selecting models

### Embedding Interface

The embedding functionality is abstracted through `EmbeddingInterface` defined in [src/rag/interfaces/embedding_interface.py](../../rag/interfaces/embedding_interface.py). Key methods:

- `embed_texts(texts: List[str]) -> List[List[float]]`: Batch embedding
- `embed_text(text: str) -> List[float]`: Single text embedding

## Supported Providers

### 1. OpenAI

**Location**: [src/providers/openai/](../openai/)

- Uses OpenAI API (GPT models, text-embedding models)
- Configured via `OPENAI_API_KEY` environment variable
- Adapter: [src/providers/adapters/openai_adapter.py](../adapters/openai_adapter.py)

### 2. Ollama

**Location**: [src/providers/ollama/](../ollama/)

- Local LLM provider
- Requires Ollama server running locally
- Configured via `OLLAMA_BASE_URL` (default: http://localhost:11434)
- Adapter: [src/providers/ollama/adapter.py](../ollama/adapter.py)

### 3. LM Studio

**Location**: [src/providers/lmstudio/](../lmstudio/)

- Local LLM provider with OpenAI-compatible API
- Includes caching support via `CachedEmbeddingService`
- Configured via `LMSTUDIO_BASE_URL` (default: http://localhost:1234)
- Adapter: [src/providers/adapters/lmstudio_adapter.py](../adapters/lmstudio_adapter.py)

### 4. HuggingFace

**Location**: [src/providers/huggingface/](../huggingface/)

- Inference API integration
- Configured via `HUGGINGFACE_API_KEY`
- Adapter: [src/providers/huggingface/adapter.py](../huggingface/adapter.py)

### 5. LiteLLM Gateway

**Location**: [src/providers/litellm_gateway/](../litellm_gateway/)

- Unified gateway for multiple providers
- Configured via `LITELLM_BASE_URL`
- Adapter: [src/providers/litellm_gateway/adapter.py](../litellm_gateway/adapter.py)

### 6. Local GPU

**Location**: [src/providers/local_gpu/](../local_gpu/)

- Direct GPU acceleration using sentence-transformers
- Optimal for on-premise deployments
- Configured via `RAG_EMBED_MODEL` (default: all-MiniLM-L6-v2)
- See: [LOCAL_GPU_EMBEDDINGS.md](LOCAL_GPU_EMBEDDINGS.md)

## Provider Selection

The provider is selected based on configuration in [src/rag/conf.py](../../rag/conf.py):

```python
# Example configuration priority:
1. RAG_PROVIDER environment variable
2. Default provider from settings
3. Fallback to OpenAI
```

## Provider Registry

The [src/providers/registry.py](../registry.py) and [src/providers/app_registry.py](../app_registry.py) modules manage:

- Provider registration
- Provider discovery
- Provider instantiation with configuration

## Caching Layer

Many providers support optional Redis caching for embeddings:

- **Implementation**: [src/providers/lmstudio/cached_embeddings.py](../lmstudio/cached_embeddings.py)
- **Configuration**:
  - `RAG_EMBED_CACHE_ENABLED`: Enable/disable (default: true)
  - `RAG_EMBED_CACHE_TTL`: Cache TTL in seconds (default: 604800 = 7 days)
  - `RAG_EMBED_CACHE_PREFIX`: Cache key prefix (default: "embed:")
  - `RAG_EMBED_CACHE_DB`: Redis database (default: 0)

## Adding a New Provider

To add a new provider:

1. **Create provider directory**: `src/providers/newprovider/`
2. **Implement adapter**: Extend `ProviderAdapterInterface`
3. **Implement embedding service** (optional): Extend `EmbeddingInterface`
4. **Register provider**: Update `app_registry.py`
5. **Add configuration**: Update `src/rag/conf.py` and `.env`
6. **Document**: Add to this file and create provider-specific docs

### Example Structure

```
src/providers/newprovider/
├── __init__.py
├── adapter.py         # ProviderAdapterInterface implementation
├── client.py          # API client (optional)
├── embeddings.py      # EmbeddingInterface implementation (optional)
└── apps.py            # Application registration
```

## Testing Providers

Provider tests are located in:
- Unit tests: [tests/unit/test_embeddings.py](../../../tests/unit/test_embeddings.py)
- Integration tests: [tests/integration/test_api.py](../../../tests/integration/test_api.py)

## Related Documentation

- [Embedding Factory](../../rag/embeddings_factory.py): Factory for creating embedding instances
- [RAG Engine](../../rag/engine.py): How providers are used in the RAG pipeline
- [API Routers](../../api/routers/): Provider usage in API endpoints
