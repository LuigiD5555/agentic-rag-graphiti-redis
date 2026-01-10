"""HTTP client for rag-tool-office service."""
import os
import tempfile
from pathlib import Path
from typing import Literal, Optional

import requests
from langchain_core.documents import Document
from src.rag.conf import Config

_config = Config()


class OfficeToolClient:
    """Client to convert Office documents via rag-tool-office HTTP service."""

    def __init__(self, base_url: Optional[str] = None):
        """Initialize the client.

        Args:
            base_url: Base URL for rag-tool-office (default: http://127.0.0.1:9102)
        """
        self.base_url = base_url or os.getenv("TOOL_OFFICE_URL", "http://127.0.0.1:9102")
        self.timeout = int(os.getenv("TOOL_OFFICE_TIMEOUT", "120"))

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

        try:
            # Call rag-tool-office HTTP API
            response = requests.post(
                f"{self.base_url}/convert",
                json={
                    "input_path": str(input_path),
                    "output_format": "txt",
                    "output_path": output_path,
                },
                timeout=self.timeout,
            )

            if response.status_code != 200:
                raise RuntimeError(
                    f"Office conversion failed (HTTP {response.status_code}): "
                    f"{response.text}"
                )

            result = response.json()

            if not result.get("success"):
                error_msg = result.get("error", "Unknown error")
                raise RuntimeError(f"Office conversion failed: {error_msg}")

            # Read converted text
            output_file = Path(result["output_path"])
            if not output_file.exists():
                raise RuntimeError(f"Output file not found: {output_file}")

            return output_file.read_text(encoding="utf-8", errors="replace")

        finally:
            # Clean up temp file
            if Path(output_path).exists():
                Path(output_path).unlink()

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
        """Check if rag-tool-office service is available.

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
