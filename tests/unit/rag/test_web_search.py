"""Tests for async SearXNG web search client."""

import httpx
import pytest
from unittest.mock import AsyncMock, MagicMock
from pytest_readable import readable

from src.apps.websearch.searxng_client import SearXNGClient


def _make_async_client(*, json_payload=None, status_code=200, exception=None):
    """Build an async HTTP client mock."""
    if exception:
        get = AsyncMock(side_effect=exception)
    else:
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = json_payload or {}
        response.raise_for_status = MagicMock()
        get = AsyncMock(return_value=response)

    client = MagicMock()
    client.get = get
    return client


def _patch_client(searxng_client, async_client):
    async def _get_client():
        return async_client
    searxng_client._get_client = _get_client


@pytest.mark.asyncio
class TestSearXNGClientAsync:
    """Test async SearXNGClient."""

    @readable(
        intent="Verify that search transforms SearXNG results correctly.",
        steps=[
            "Provide a 200 response with two results",
            "Run search with a query",
            "Validate output fields and positional scores",
        ],
        criteria=[
            "Two results are returned",
            "Each result contains title, URL, and the expected score",
        ],
    )
    async def test_search_returns_results(self):
        client = SearXNGClient(base_url="http://localhost:8080", max_results=3)
        payload = {
            "results": [
                {"title": "Result 1", "content": "Content 1", "url": "https://example.com/1", "engine": "google", "category": "general"},
                {"title": "Result 2", "content": "Content 2", "url": "https://example.com/2", "engine": "duckduckgo", "category": "general"},
            ]
        }
        _patch_client(client, _make_async_client(json_payload=payload))

        results = await client.search("test query")

        assert len(results) == 2
        assert results[0]["title"] == "Result 1"
        assert results[0]["url"] == "https://example.com/1"
        assert results[0]["score"] == 1.0
        assert results[1]["score"] == 0.9

    @readable(
        intent="Ensure search handles timeouts without breaking the flow.",
        steps=[
            "Force the HTTP client to raise TimeoutException",
            "Run search",
        ],
        criteria=[
            "Timeout results in an empty list",
        ],
    )
    async def test_search_handles_timeout(self):
        client = SearXNGClient(base_url="http://localhost:8080", timeout=1.0)
        _patch_client(client, _make_async_client(exception=httpx.TimeoutException("Timeout")))

        assert await client.search("test query") == []

    @readable(
        intent="Ensure search handles HTTP errors with a safe fallback.",
        steps=[
            "Simulate an HTTPStatusError",
            "Run search",
        ],
        criteria=[
            "HTTP errors produce an empty list",
        ],
    )
    async def test_search_handles_http_error(self):
        client = SearXNGClient(base_url="http://localhost:8080")
        error = httpx.HTTPStatusError(
            "500 Server Error",
            request=httpx.Request("GET", "http://localhost:8080"),
            response=httpx.Response(500),
        )
        _patch_client(client, _make_async_client(exception=error))

        assert await client.search("test query") == []

    @readable(
        intent="Cover forwarding categories and engines in the search request.",
        steps=[
            "Run search with categories and engines",
            "Check HTTP parameters",
        ],
        criteria=[
            "Params include comma-separated categories and engines",
            "Mandatory q, format=json, and language keys are present",
        ],
    )
    async def test_search_sends_categories_and_engines_params(self):
        client = SearXNGClient(base_url="http://localhost:8080")
        async_client = _make_async_client(json_payload={"results": []})
        _patch_client(client, async_client)

        await client.search(
            "test query",
            categories=["news", "science"],
            engines=["duckduckgo", "google"],
        )

        params = async_client.get.call_args[1]["params"]
        assert params["q"] == "test query"
        assert params["format"] == "json"
        assert params["language"] == client.language
        assert params["categories"] == "news,science"
        assert params["engines"] == "duckduckgo,google"

    @readable(
        intent="Validate that search_and_format creates RAG-compatible documents.",
        steps=[
            "Provide a single web search result",
            "Run search_and_format",
            "Inspect resulting document",
        ],
        criteria=[
            "Document exposes uuid, text, source, chunk_index, score, distance, and _metadata",
            "Text includes title and content",
        ],
    )
    async def test_search_and_format_returns_rag_format(self):
        client = SearXNGClient(base_url="http://localhost:8080")
        payload = {
            "results": [
                {
                    "title": "Test Doc",
                    "content": "This is test content",
                    "url": "https://example.com/test",
                    "engine": "google",
                    "category": "general",
                },
            ]
        }
        _patch_client(client, _make_async_client(json_payload=payload))

        docs = await client.search_and_format("test query")

        assert len(docs) == 1
        doc = docs[0]
        assert "uuid" in doc
        assert "text" in doc
        assert "source" in doc
        assert "chunk_index" in doc
        assert "score" in doc
        assert "distance" in doc
        assert "_metadata" in doc
        assert doc["uuid"].startswith("web_")
        assert "# Test Doc" in doc["text"]
        assert "This is test content" in doc["text"]
        assert doc["source"] == "https://example.com/test"
        assert doc["chunk_index"] == 0
        assert doc["distance"] is None

    @readable(
        intent="Confirm is_available checks healthz and detects positive availability.",
        steps=[
            "Provide a healthy response",
            "Run is_available",
        ],
        criteria=[
            "Returns True when health endpoint responds with 200",
        ],
    )
    async def test_is_available_checks_health(self):
        client = SearXNGClient(base_url="http://localhost:8080")
        _patch_client(client, _make_async_client(status_code=200))

        assert await client.is_available() is True

    @readable(
        intent="Ensure is_available returns False when health check fails.",
        steps=[
            "Force a connection error",
            "Run is_available",
        ],
        criteria=[
            "Returns False when the health endpoint cannot be reached",
        ],
    )
    async def test_is_available_handles_failure(self):
        client = SearXNGClient(base_url="http://localhost:8080")
        _patch_client(client, _make_async_client(exception=httpx.ConnectError("Connection refused")))

        assert await client.is_available() is False

    @readable(
        intent="Verify client lifecycle behavior in async context manager usage.",
        steps=[
            "Enter the async context manager",
            "Exit and observe cleanup",
        ],
        criteria=[
            "The client stays usable inside the context and closes afterwards",
        ],
    )
    async def test_client_lifecycle(self):
        async with SearXNGClient(base_url="http://localhost:8080") as client:
            assert client is not None

    @readable(
        intent="Validate that close shuts down AsyncClient and clears internal reference.",
        steps=[
            "Assign a stubbed AsyncClient",
            "Call close",
        ],
        criteria=[
            "aclose is called exactly once",
            "_client is cleared",
        ],
    )
    async def test_close_closes_client(self):
        client = SearXNGClient(base_url="http://localhost:8080")
        stub = MagicMock()
        stub.aclose = AsyncMock()
        stub.is_closed = False  # must be False so close() proceeds with aclose()
        client._client = stub

        await client.close()

        stub.aclose.assert_called_once()
        assert client._client is None
