"""Tests for async SearXNG web search client."""
import pytest
import httpx
from unittest.mock import AsyncMock, Mock, patch
from src.apps.websearch.searxng_client import SearXNGClient


@pytest.mark.asyncio
class TestSearXNGClientAsync:
    """Test async SearXNGClient."""

    async def test_search_returns_results(self):
        """Test that search() returns formatted results."""
        client = SearXNGClient(
            base_url="http://localhost:8080",
            max_results=3,
        )

        # Mock httpx response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "results": [
                {
                    "title": "Test Result 1",
                    "content": "Content 1",
                    "url": "https://example.com/1",
                    "engine": "google",
                    "category": "general",
                },
                {
                    "title": "Test Result 2",
                    "content": "Content 2",
                    "url": "https://example.com/2",
                    "engine": "duckduckgo",
                    "category": "general",
                },
            ]
        }

        # Mock async client
        with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get:
            mock_http_client = AsyncMock()
            mock_http_client.get = AsyncMock(return_value=mock_response)
            mock_get.return_value = mock_http_client

            results = await client.search("test query")

            # Assert results
            assert len(results) == 2
            assert results[0]["title"] == "Test Result 1"
            assert results[0]["url"] == "https://example.com/1"
            assert results[0]["score"] == 1.0  # First result
            assert results[1]["score"] == 0.9  # Second result

    async def test_search_handles_timeout(self):
        """Test that search() handles timeout gracefully."""
        client = SearXNGClient(
            base_url="http://localhost:8080",
            timeout=1.0,
        )

        # Mock timeout
        with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get:
            mock_http_client = AsyncMock()
            mock_http_client.get = AsyncMock(
                side_effect=httpx.TimeoutException("Timeout")
            )
            mock_get.return_value = mock_http_client

            results = await client.search("test query")

            # Assert empty results on timeout
            assert results == []

    async def test_search_handles_http_error(self):
        """Test that search() handles HTTP errors gracefully."""
        client = SearXNGClient(base_url="http://localhost:8080")

        # Mock HTTP error
        with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get:
            mock_http_client = AsyncMock()
            mock_request = Mock()
            mock_http_client.get = AsyncMock(
                side_effect=httpx.HTTPStatusError(
                    "500 Server Error",
                    request=mock_request,
                    response=Mock(status_code=500)
                )
            )
            mock_get.return_value = mock_http_client

            results = await client.search("test query")

            # Assert empty results on error
            assert results == []

    async def test_search_and_format_returns_rag_format(self):
        """Test that search_and_format() returns RAG-compatible docs."""
        client = SearXNGClient(base_url="http://localhost:8080")

        # Mock httpx response
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
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

        # Mock async client
        with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get:
            mock_http_client = AsyncMock()
            mock_http_client.get = AsyncMock(return_value=mock_response)
            mock_get.return_value = mock_http_client

            docs = await client.search_and_format("test query")

            # Assert RAG format
            assert len(docs) == 1
            doc = docs[0]

            # Check required fields
            assert "uuid" in doc
            assert "text" in doc
            assert "source" in doc
            assert "chunk_index" in doc
            assert "score" in doc
            assert "distance" in doc
            assert "_metadata" in doc

            # Check values
            assert doc["uuid"].startswith("web_")
            assert "# Test Doc" in doc["text"]
            assert "This is test content" in doc["text"]
            assert doc["source"] == "https://example.com/test"
            assert doc["chunk_index"] == 0
            assert doc["distance"] is None

    async def test_is_available_checks_health(self):
        """Test that is_available() checks health endpoint."""
        client = SearXNGClient(base_url="http://localhost:8080")

        # Mock successful health check
        mock_response = Mock()
        mock_response.status_code = 200

        with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get:
            mock_http_client = AsyncMock()
            mock_http_client.get = AsyncMock(return_value=mock_response)
            mock_get.return_value = mock_http_client

            available = await client.is_available()

            # Assert available
            assert available is True

    async def test_is_available_handles_failure(self):
        """Test that is_available() returns False on failure."""
        client = SearXNGClient(base_url="http://localhost:8080")

        # Mock failed health check
        with patch.object(client, "_get_client", new_callable=AsyncMock) as mock_get:
            mock_http_client = AsyncMock()
            mock_http_client.get = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            mock_get.return_value = mock_http_client

            available = await client.is_available()

            # Assert not available
            assert available is False

    async def test_client_lifecycle(self):
        """Test async context manager lifecycle."""
        async with SearXNGClient(base_url="http://localhost:8080") as client:
            # Client should be usable
            assert client is not None

        # Client should be closed after context
        # (we can't easily test this without real client)

    async def test_close_closes_client(self):
        """Test that close() closes the HTTP client."""
        client = SearXNGClient(base_url="http://localhost:8080")

        # Create mock client
        mock_http_client = AsyncMock()
        mock_http_client.is_closed = False
        mock_http_client.aclose = AsyncMock()
        client._client = mock_http_client

        await client.close()

        # Assert aclose was called
        mock_http_client.aclose.assert_called_once()
        assert client._client is None
