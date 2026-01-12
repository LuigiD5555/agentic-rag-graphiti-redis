"""SearXNG client for web search fallback in RAG pipeline."""
import time
import hashlib
from typing import List, Dict, Any, Optional
import httpx
from src.workflows.query.audit import get_logger

log = get_logger(__name__)


class SearXNGClient:
    """Async client for SearXNG metasearch engine."""

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        timeout: float = 10.0,
        max_results: int = 5,
        language: str = "es",
    ):
        """Initialize SearXNG client.

        Args:
            base_url: SearXNG instance URL.
            timeout: Request timeout in seconds.
            max_results: Maximum number of results to return.
            language: Search language (es, en, etc.).
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_results = max_results
        self.language = language
        self.search_endpoint = f"{self.base_url}/search"
        self._client: Optional[httpx.AsyncClient] = None

        log.info(
            "Initialized SearXNGClient: base_url=%s, timeout=%.1fs, max_results=%d, lang=%s",
            base_url, timeout, max_results, language
        )

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self):
        """Close the async HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()

    async def search(
        self,
        query: str,
        categories: Optional[List[str]] = None,
        engines: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Perform async web search using SearXNG.

        Args:
            query: Search query.
            categories: Optional categories (general, news, science, etc.).
            engines: Optional specific engines to use.

        Returns:
            List of search results with title, content, url, score.
        """
        start_time = time.time()

        try:
            # Build request parameters
            params = {
                "q": query,
                "format": "json",
                "language": self.language,
            }

            if categories:
                params["categories"] = ",".join(categories)

            if engines:
                params["engines"] = ",".join(engines)

            log.debug("Searching SearXNG: query=%s, params=%s", query[:50], params)

            # Make async request
            client = await self._get_client()
            response = await client.get(
                self.search_endpoint,
                params=params,
            )
            response.raise_for_status()

            search_time = time.time() - start_time
            log.info("SearXNG search completed in %.3fs", search_time)

            # Parse results
            data = response.json()
            raw_results = data.get("results", [])

            # Convert to our format
            results = []
            for i, result in enumerate(raw_results[:self.max_results]):
                processed = {
                    "title": result.get("title", ""),
                    "content": result.get("content", ""),
                    "url": result.get("url", ""),
                    "engine": result.get("engine", ""),
                    "category": result.get("category", "general"),
                    # Score based on position (1.0 for first, decreasing)
                    "score": 1.0 - (i * 0.1),
                    "source": "web_search",
                }
                results.append(processed)

            log.info("Retrieved %d web search results", len(results))
            return results

        except httpx.TimeoutException:
            elapsed = time.time() - start_time
            log.error("SearXNG search timeout after %.3fs", elapsed)
            return []

        except httpx.HTTPStatusError as e:
            elapsed = time.time() - start_time
            log.error("SearXNG search failed after %.3fs: %s", elapsed, e)
            return []

        except httpx.RequestError as e:
            elapsed = time.time() - start_time
            log.error("SearXNG request error after %.3fs: %s", elapsed, e)
            return []

        except Exception as e:
            elapsed = time.time() - start_time
            log.error(
                "Unexpected error in web search after %.3fs: %s",
                elapsed, e, exc_info=True
            )
            return []

    async def search_and_format(
        self,
        query: str,
        categories: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Search and format results for RAG context.

        This formats results to match the structure expected by the RAG orchestrator.

        Args:
            query: Search query.
            categories: Optional search categories.

        Returns:
            List of results formatted like retrieved documents:
            - uuid: Unique identifier
            - text: Combined title + content
            - source: URL
            - chunk_index: Always 0 for web results
            - score: Relevance score
        """
        results = await self.search(query, categories=categories)

        formatted = []
        for i, result in enumerate(results):
            # Combine title and content into text
            text_parts = []
            if result.get("title"):
                text_parts.append(f"# {result['title']}")
            if result.get("content"):
                text_parts.append(result["content"])

            text = "\n\n".join(text_parts)

            # Generate stable UUID from URL using deterministic hash
            url = result.get('url', '')
            url_hash = hashlib.sha256(url.encode()).hexdigest()[:16]

            formatted_doc = {
                "uuid": f"web_{url_hash}",
                "text": text,
                "source": result.get("url", "web_search"),
                "chunk_index": 0,
                "score": result.get("score", 0.5),
                "distance": None,  # Not applicable for web search
                "_metadata": {
                    "engine": result.get("engine", ""),
                    "category": result.get("category", "general"),
                    "source_type": "web_search",
                }
            }
            formatted.append(formatted_doc)

        return formatted

    async def is_available(self) -> bool:
        """Check if SearXNG instance is available.

        Returns:
            True if SearXNG is reachable, False otherwise.
        """
        try:
            client = await self._get_client()
            response = await client.get(
                f"{self.base_url}/healthz",
                timeout=3.0,
            )
            return response.status_code == 200
        except Exception:
            return False


__all__ = ["SearXNGClient"]
