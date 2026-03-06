# Providers Architecture

This document describes the provider system architecture in the RAG project.

## Overview

The provider system implements an adapter pattern to support multiple LLM and embedding APIs with a unified interface. This allows the application to seamlessly switch between different providers (OpenAI, Ollama, LM Studio, HuggingFace, etc.) without changing business logic.

## Core Concepts

### Provider Adapter Interface

All providers implement the `ProviderAdapterInterface` defined in `src/workflows/query/interfaces/provider_adapter_interface.py`. This interface defines:

- **Chat methods**: For conversational interactions
- **Embedding methods**: For text vectorization

### Embedding Interface

The embedding functionality is abstracted through `EmbeddingInterface` defined in `src/workflows/query/interfaces/embedding_interface.py`. Key methods:

- `embed_texts(texts: List[str]) -> List[List[float]]`: Batch embedding
- `embed_text(text: str) -> List[float]`: Single text embedding

## Supported Providers

### 1. OpenAI

**Location**: `src/backends/llm/openai/`

- Uses OpenAI API (GPT models, text-embedding models)
- Configured via `OPENAI_API_KEY` environment variable
- Adapter: `src/backends/llm/adapters/openai_adapter.py`

### 2. Ollama

**Location**: `src/backends/llm/ollama/`

- Local LLM provider
- Requires Ollama server running locally
- Configured via `OLLAMA_BASE_URL` (default: http://localhost:11434)
- Adapter: `src/backends/llm/ollama/adapter.py`

### 3. LM Studio

**Location**: `src/backends/llm/lmstudio/`

- Local LLM provider with OpenAI-compatible API
- Configured via `LMSTUDIO_BASE_URL` (default: http://localhost:1234)
- Adapter: `src/backends/llm/adapters/lmstudio_adapter.py`

### 4. HuggingFace

**Location**: `src/backends/llm/huggingface/`

- Inference API integration
- Configured via `HUGGINGFACE_API_KEY`
- Adapter: `src/backends/llm/huggingface/adapter.py`

### 5. LiteLLM Gateway

**Location**: `src/backends/llm/litellm_gateway/`

- Unified gateway for multiple providers
- Configured via `LITELLM_BASE_URL`
- Adapter: `src/backends/llm/litellm_gateway/adapter.py`

## Provider Selection

The provider is selected based on configuration in `src/backends/llm/factory.py` (settings `PROVIDER` or `PROVIDERS`):

```python
# Example configuration priority:
1. `PROVIDER` environment variable
2. Default provider from `PROVIDERS.default` in settings
3. Fallback to `lmstudio`
```

## Provider Registry

The `src/backends/llm/registry.py` and `src/backends/llm/app_registry.py` modules manage:

- Provider registration
- Provider discovery
- Provider instantiation with configuration

## Adding a New Provider

To add a new provider:

1. **Create provider directory**: `src/backends/llm/newprovider/`
2. **Implement adapter**: Extend `ProviderAdapterInterface`
3. **Implement embedding service** (optional): Extend `EmbeddingInterface`
4. **Register provider**: Update `app_registry.py`
5. **Add configuration**: Update `src/settings.py` or `data/settings.json` and `.env`
6. **Document**: Add to this file and create provider-specific docs

### Example Structure

```
src/backends/llm/newprovider/
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

- `src/backends/llm/factory.py`: Provider selection and adapter construction
- `src/workflows/query/engine.py`: How providers are used in the RAG pipeline
- `src/api/routes/`: Provider usage in API endpoints
