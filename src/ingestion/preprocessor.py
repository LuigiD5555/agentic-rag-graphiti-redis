"""File preprocessing using socket-activated tools.

This module handles automatic preprocessing of files that need conversion
before ingestion (Office docs, archives, images needing OCR, etc.).
"""

import time
from pathlib import Path
from typing import Optional, Dict, Any
import requests

from src.conf import settings
from src.rag.audit import get_logger

log = get_logger(__name__)


class FilePreprocessor:
    """Preprocesses files using socket-activated tools before ingestion."""

    def __init__(
        self,
        office_url: Optional[str] = None,
        archive_url: Optional[str] = None,
        ocr_url: Optional[str] = None,
        enable_office: bool = True,
        enable_archive: bool = True,
        enable_ocr: bool = False,  # Disabled by default (slower)
        timeout: int = 120,
        work_dir: Optional[str] = None,
    ):
        """Initialize preprocessor.

        Args:
            office_url: URL for office conversion tool
            archive_url: URL for archive extraction tool
            ocr_url: URL for OCR tool
            enable_office: Enable Office document conversion
            enable_archive: Enable archive extraction
            enable_ocr: Enable OCR for images/scanned PDFs
            timeout: Request timeout in seconds
            work_dir: Working directory for processed files
        """
        self.office_url = office_url or settings.TOOL_OFFICE_URL
        self.archive_url = archive_url or settings.TOOL_FILEEXTRACTOR_URL
        self.ocr_url = ocr_url or settings.TOOL_OCR_URL
        self.enable_office = enable_office and settings.ENABLE_OFFICE_CONVERSION
        self.enable_archive = enable_archive and settings.ENABLE_EXTRACTOR_EXTRACTION
        self.enable_ocr = enable_ocr or settings.ENABLE_OCR
        self.timeout = timeout
        self.work_dir = Path(work_dir or settings.PREPROCESSING_WORK_DIR)
        self.work_dir.mkdir(parents=True, exist_ok=True)

        # Extensions that need preprocessing
        self.office_extensions = {'.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt'}
        self.archive_extensions = {'.zip', '.7z', '.tar', '.tar.gz', '.tar.xz', '.tar.bz2', '.tgz'}
        self.ocr_extensions = {'.png', '.jpg', '.jpeg', '.tiff', '.bmp'}

        log.info(
            "FilePreprocessor initialized: office=%s, archive=%s, ocr=%s",
            self.enable_office, self.enable_archive, self.enable_ocr
        )

    def _post_with_retries(self, url: str, payload: Dict[str, Any]) -> requests.Response:
        retries = settings.TOOL_CONNECT_RETRIES
        delay = settings.TOOL_CONNECT_RETRY_DELAY
        last_exc = None
        for _ in range(max(1, retries)):
            try:
                return requests.post(url, json=payload, timeout=self.timeout)
            except requests.exceptions.ConnectionError as exc:
                last_exc = exc
                time.sleep(delay)
        raise requests.exceptions.ConnectionError(str(last_exc))

    def should_preprocess(self, file_path: Path) -> bool:
        """Check if a file needs preprocessing.

        Args:
            file_path: Path to file

        Returns:
            True if file needs preprocessing
        """
        suffix = file_path.suffix.lower()

        if self.enable_office and suffix in self.office_extensions:
            return True

        if self.enable_archive and suffix in self.archive_extensions:
            return True

        if self.enable_ocr and suffix in self.ocr_extensions:
            return True

        return False

    def preprocess(self, file_path: Path) -> Optional[Path]:
        """Preprocess a file if needed.

        Args:
            file_path: Path to input file

        Returns:
            Path to processed file, or original path if no preprocessing needed,
            or None if preprocessing failed
        """
        if not self.should_preprocess(file_path):
            return file_path

        suffix = file_path.suffix.lower()

        try:
            # Office documents -> convert to text
            if self.enable_office and suffix in self.office_extensions:
                return self._convert_office_document(file_path)

            # Archives -> extract (returns directory)
            elif self.enable_archive and suffix in self.archive_extensions:
                return self._extract_archive(file_path)

            # Images -> OCR
            elif self.enable_ocr and suffix in self.ocr_extensions:
                return self._perform_ocr(file_path)

            else:
                return file_path

        except Exception as e:
            log.error("Preprocessing failed for %s: %s", file_path, e)
            return None

    def _convert_office_document(self, file_path: Path) -> Optional[Path]:
        """Convert Office document to text.

        Args:
            file_path: Path to Office document

        Returns:
            Path to converted text file, or None if failed
        """
        log.info("Converting Office document: %s", file_path)

        try:
            response = self._post_with_retries(
                f"{self.office_url}/convert",
                {
                    "input_path": str(file_path.absolute()),
                    "output_format": "txt",
                },
            )
            response.raise_for_status()
            result = response.json()

            if result.get("success"):
                output_path = Path(result["output_path"])
                log.info("Successfully converted %s -> %s", file_path.name, output_path.name)
                return output_path

            log.error("Office conversion failed: %s", result.get("error"))
            log.info("Falling back to direct ingestion for %s", file_path.name)
            return file_path

        except requests.exceptions.ConnectionError:
            log.warning(
                "Office tool not available at %s. "
                "Make sure socket is enabled: systemctl --user status tool-office.socket",
                self.office_url
            )
            log.info("Falling back to direct ingestion for %s", file_path.name)
            return file_path
        except Exception as e:
            log.error("Office conversion error: %s", e)
            log.info("Falling back to direct ingestion for %s", file_path.name)
            return file_path

    def convert_office_document(self, file_path: Path) -> Optional[Path]:
        """Public wrapper to convert an Office document to text."""
        return self._convert_office_document(file_path)

    def _extract_archive(self, file_path: Path) -> Optional[Path]:
        """Extract archive.

        Args:
            file_path: Path to archive file

        Returns:
            Path to extraction directory, or None if failed
        """
        log.info("Extracting archive: %s", file_path)

        try:
            response = self._post_with_retries(
                f"{self.archive_url}/extract",
                {
                    "archive_path": str(file_path.absolute()),
                    "max_size_mb": settings.ARCHIVE_MAX_SIZE_MB,
                },
            )
            response.raise_for_status()
            result = response.json()

            if result.get("success"):
                output_dir = Path(result["output_dir"])
                file_count = result.get("file_count", 0)
                total_size_mb = result.get("total_size_mb", 0)

                log.info(
                    "Successfully extracted %s -> %s (%d files, %.2f MB)",
                    file_path.name, output_dir.name, file_count, total_size_mb
                )
                return output_dir
            else:
                log.error("Archive extraction failed: %s", result.get("error"))
                return None

        except requests.exceptions.ConnectionError:
            log.warning(
                "Archive tool not available at %s. "
                "Make sure socket is enabled: systemctl --user status tool-extractor.socket",
                self.archive_url
            )
            return None
        except Exception as e:
            log.error("Archive extraction error: %s", e)
            return None

    def extract_archive(self, file_path: Path) -> Optional[Path]:
        """Public wrapper to extract an archive."""
        return self._extract_archive(file_path)

    def _perform_ocr(self, file_path: Path) -> Optional[Path]:
        """Perform OCR on image.

        Args:
            file_path: Path to image file

        Returns:
            Path to OCR'd text file, or None if failed
        """
        log.info("Performing OCR on: %s", file_path)

        try:
            response = self._post_with_retries(
                f"{self.ocr_url}/ocr",
                {
                    "input_path": str(file_path.absolute()),
                    "language": settings.OCR_DEFAULT_LANGUAGE,
                    "output_format": "txt",
                },
            )
            response.raise_for_status()
            result = response.json()

            if result.get("success"):
                output_path = Path(result["output_path"])
                log.info("Successfully OCR'd %s -> %s", file_path.name, output_path.name)
                return output_path
            else:
                log.error("OCR failed: %s", result.get("error"))
                return None

        except requests.exceptions.ConnectionError:
            log.warning(
                "OCR tool not available at %s. "
                "Make sure socket is enabled: systemctl --user status tool-ocr.socket",
                self.ocr_url
            )
            return None

    def perform_ocr(self, file_path: Path) -> Optional[Path]:
        """Public wrapper to perform OCR on an image file."""
        try:
            return self._perform_ocr(file_path)
        except Exception as e:
            log.error("OCR error: %s", e)
            return None

    def get_status(self) -> Dict[str, Any]:
        """Get preprocessor status.

        Returns:
            Dict with tool availability and configuration
        """
        status = {
            "enabled": {
                "office": self.enable_office,
                "archive": self.enable_archive,
                "ocr": self.enable_ocr,
            },
            "tools_available": {},
        }

        # Check if tools are reachable
        for name, url in [
            ("office", self.office_url),
            ("archive", self.archive_url),
            ("ocr", self.ocr_url),
        ]:
            try:
                response = requests.get(f"{url}/healthz", timeout=2)
                status["tools_available"][name] = response.status_code == 200
            except:
                status["tools_available"][name] = False

        return status


# Singleton instance
_preprocessor_instance: Optional[FilePreprocessor] = None


def get_preprocessor(**kwargs) -> FilePreprocessor:
    """Get or create FilePreprocessor singleton.

    Args:
        **kwargs: Arguments to pass to FilePreprocessor constructor

    Returns:
        FilePreprocessor instance
    """
    global _preprocessor_instance
    if _preprocessor_instance is None:
        _preprocessor_instance = FilePreprocessor(**kwargs)
    return _preprocessor_instance
