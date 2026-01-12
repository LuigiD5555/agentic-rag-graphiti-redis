"""HTTP client for rag-tool-document-processor service."""
import tempfile
from pathlib import Path
from typing import Literal, Optional

import requests
from langchain_core.documents import Document

from src.conf import settings
from src.workflows.query.audit import get_logger

log = get_logger(__name__)


class OfficeToolClient:
    """Client to convert Office documents via rag-tool-document-processor HTTP service."""

    def __init__(self, base_url: Optional[str] = None):
        """Initialize the client.

        Args:
            base_url: Base URL for rag-tool-document-processor (default: from settings)
        """
        self.base_url = base_url or settings.TOOL_OFFICE_URL
        self.timeout = settings.TOOL_OFFICE_TIMEOUT

    def convert_to_text(self, input_path: str) -> str:
        """Convert Office document to plain text.

        Args:
            input_path: Path to the Office document

        Returns:
            Extracted text content

        Raises:
            RuntimeError: If conversion fails
        """
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
            output_path = tmp.name

        payload = {
            "input_path": str(input_path),
            "output_format": "txt",
            "output_path": output_path,
        }

        urls_to_try = [self.base_url]

        last_exception = None
        try:
            for service_url in urls_to_try:
                try:
                    result = self._call_convert_service(service_url, payload)
                    output_file = Path(result["output_path"])
                    if not output_file.exists():
                        raise RuntimeError(f"Output file not found: {output_file}")

                    return output_file.read_text(encoding="utf-8", errors="replace")
                except requests.RequestException as exc:
                    last_exception = exc
                    log.warning("Tool-office unavailable (%s): %s", service_url, exc)
                    continue

            error_hint = (
                "No available Office conversion service" if last_exception else "No service configured"
            )
            raise RuntimeError(
                f"Office conversion failed: {error_hint}"
            ) from last_exception

        finally:
            # Clean up temp file
            if Path(output_path).exists():
                Path(output_path).unlink()

    def _call_convert_service(self, service_url: str, payload: dict) -> dict:
        response = requests.post(
            f"{service_url}/convert",
            json=payload,
            timeout=self.timeout,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Office conversion failed (HTTP {response.status_code}): {response.text}"
            )

        result = response.json()

        if not result.get("success"):
            error_msg = result.get("error", "Unknown error")
            raise RuntimeError(f"Office conversion failed: {error_msg}")

        return result

    def load_as_document(self, input_path: str) -> Document:
        """Load Office document as LangChain Document.

        Args:
            input_path: Path to the Office document

        Returns:
            LangChain Document with extracted text

        Raises:
            RuntimeError: If conversion fails
        """
        text = self.convert_to_text(input_path)

        return Document(
            page_content=text,
            metadata={
                "source": str(input_path),
                "file_path": str(input_path),
            },
        )

    def health_check(self) -> bool:
        """Check if rag-tool-document-processor service is available.

        Returns:
            True if service is healthy, False otherwise
        """
        try:
            response = requests.get(
                f"{self.base_url}/healthz",
                timeout=5,
            )
            return response.status_code == 200
        except Exception:
            return False
