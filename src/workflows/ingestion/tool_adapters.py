"""Adapters for socket-activated preprocessing tools."""

import time
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Optional

import requests

from src.conf import settings
from src.workflows.query.audit import get_logger

log = get_logger(__name__)


class ToolAdapter(ABC):
    """Base class for communicating with a socket-activated tool."""

    name: str

    def __init__(
        self,
        base_url: str,
        timeout: int,
        retries: int,
        retry_delay: float,
        enabled: bool = True,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = timeout
        self.retries = max(1, retries)
        self.retry_delay = retry_delay
        self.enabled = enabled and bool(self.base_url)

    def request_url(self, endpoint: str) -> str:
        return f"{self.base_url}/{endpoint.lstrip('/')}"

    def _post_with_retries(self, endpoint: str, payload: Dict[str, Any]) -> requests.Response:
        last_exc: Optional[Exception] = None
        for _ in range(self.retries):
            try:
                return requests.post(
                    self.request_url(endpoint),
                    json=payload,
                    timeout=self.timeout,
                )
            except requests.exceptions.ConnectionError as exc:
                last_exc = exc
                time.sleep(self.retry_delay)
        raise requests.exceptions.ConnectionError(str(last_exc))

    def health_check(self) -> bool:
        if not self.enabled:
            return False
        try:
            response = requests.get(self.request_url("/healthz"), timeout=min(2, self.timeout))
            return response.status_code == 200
        except requests.RequestException:
            log.debug("[%s] health check failed", self.name, exc_info=True)
            return False

    def is_available(self) -> bool:
        return self.enabled and self.health_check()

    @abstractmethod
    def process(self, file_path: Path) -> Optional[Path]:
        """Run the adapter against the given file."""
        ...


class OfficeToolAdapter(ToolAdapter):
    name = "office"
    
    # Semaphore to limit concurrent requests to Office service
    # Default: 3 concurrent requests max
    _concurrent_requests_semaphore = threading.Semaphore(3)

    def process(self, file_path: Path) -> Optional[Path]:
        if not self.enabled:
            return file_path
        
        # Acquire semaphore to limit concurrent requests
        if not self._concurrent_requests_semaphore.acquire(timeout=30):
            log.warning("Timeout waiting for Office service slot for %s", file_path.name)
            return None
        
        try:
            payload = {
                "input_path": str(file_path.absolute()),
                "output_format": "txt",
            }
            
            response = self._post_with_retries("convert", payload)
            response.raise_for_status()
            result = response.json()
            
            if result.get("success"):
                output_path = Path(result["output_path"])
                log.info("Tool-document-processor converted %s -> %s", file_path.name, output_path.name)
                return output_path
            
            log.error("Tool-document-processor conversion failed: %s", result.get("error"))
            
        except requests.RequestException as exc:
            log.warning("Tool-document-processor unavailable: %s", exc)
        finally:
            # Always release the semaphore
            self._concurrent_requests_semaphore.release()
        
        return None


class ArchiveToolAdapter(ToolAdapter):
    name = "archive"

    def __init__(
        self,
        base_url: str,
        timeout: int,
        retries: int,
        retry_delay: float,
        enabled: bool,
        max_size_mb: int,
    ) -> None:
        super().__init__(base_url, timeout, retries, retry_delay, enabled)
        self.max_size_mb = max_size_mb

    def process(self, file_path: Path) -> Optional[Path]:
        if not self.enabled:
            return None
        payload = {
            "archive_path": str(file_path.absolute()),
            "max_size_mb": self.max_size_mb,
        }
        try:
            response = self._post_with_retries("extract", payload)
            response.raise_for_status()
            result = response.json()
            if result.get("success"):
                output_dir = Path(result["output_dir"])
                file_count = result.get("file_count", 0)
                total_mb = result.get("total_size_mb", 0)
                log.info(
                    "Tool-extractor extracted %s -> %s (%d files, %.2f MB)",
                    file_path.name,
                    output_dir.name,
                    file_count,
                    total_mb,
                )
                return output_dir
            log.error("Tool-extractor extraction failed: %s", result.get("error"))
        except requests.RequestException as exc:
            log.warning("Tool-extractor unavailable: %s", exc)
        return None


class OcrToolAdapter(ToolAdapter):
    name = "ocr"

    def process(self, file_path: Path) -> Optional[Path]:
        if not self.enabled:
            return None
        payload = {
            "input_path": str(file_path.absolute()),
            "language": settings.OCR_DEFAULT_LANGUAGE,
            "output_format": "txt",
        }
        try:
            response = self._post_with_retries("ocr", payload)
            response.raise_for_status()
            result = response.json()
            if result.get("success"):
                output_path = Path(result["output_path"])
                log.info("Tool-ocr processed %s -> %s", file_path.name, output_path.name)
                return output_path
            log.error("Tool-ocr failed: %s", result.get("error"))
        except requests.RequestException as exc:
            log.warning("Tool-ocr unavailable: %s", exc)
        return None


@dataclass
class ToolAdapterConfig:
    office_url: str
    archive_url: str
    ocr_url: str
    timeout: int
    retry_delay: float
    retries: int
    enable_office: bool
    enable_archive: bool
    enable_ocr: bool
    archive_max_size_mb: int


class ToolAdapterFactory:
    """Factory to build adapters for the preprocessing tools."""

    @staticmethod
    def build_default_adapters(config: Optional[ToolAdapterConfig] = None) -> Dict[str, ToolAdapter]:
        cfg = config or ToolAdapterConfig(
            office_url=settings.TOOL_OFFICE_URL,
            archive_url=settings.TOOL_FILEEXTRACTOR_URL,
            ocr_url=settings.TOOL_OCR_URL,
            timeout=settings.TOOL_REQUEST_TIMEOUT,
            retry_delay=settings.TOOL_CONNECT_RETRY_DELAY,
            retries=settings.TOOL_CONNECT_RETRIES,
            enable_office=settings.ENABLE_OFFICE_CONVERSION,
            enable_archive=settings.ENABLE_EXTRACTOR_EXTRACTION,
            enable_ocr=settings.ENABLE_OCR,
            archive_max_size_mb=settings.ARCHIVE_MAX_SIZE_MB,
        )
        return {
            "office": OfficeToolAdapter(
                base_url=cfg.office_url,
                timeout=cfg.timeout,
                retries=cfg.retries,
                retry_delay=cfg.retry_delay,
                enabled=cfg.enable_office,
            ),
            "archive": ArchiveToolAdapter(
                base_url=cfg.archive_url,
                timeout=cfg.timeout,
                retries=cfg.retries,
                retry_delay=cfg.retry_delay,
                enabled=cfg.enable_archive,
                max_size_mb=cfg.archive_max_size_mb,
            ),
            "ocr": OcrToolAdapter(
                base_url=cfg.ocr_url,
                timeout=cfg.timeout,
                retries=cfg.retries,
                retry_delay=cfg.retry_delay,
                enabled=cfg.enable_ocr,
            ),
        }
