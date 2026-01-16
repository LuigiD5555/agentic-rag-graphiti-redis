"""File preprocessing using socket-activated tools.

This module handles automatic preprocessing of files that need conversion
before ingestion (Office docs, archives, images needing OCR, etc.).
"""

from pathlib import Path
from typing import Dict, Any, Optional

from src.conf import settings
from src.workflows.ingestion.tool_adapters import (
    ToolAdapter,
    ToolAdapterConfig,
    ToolAdapterFactory,
)
from src.workflows.query.audit import get_logger

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
        tool_adapters: Optional[Dict[str, ToolAdapter]] = None,
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
            tool_adapters: Optional injected adapters (for testing/custom tooling)
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

        config = ToolAdapterConfig(
            office_url=self.office_url,
            archive_url=self.archive_url,
            ocr_url=self.ocr_url,
            timeout=self.timeout,
            retry_delay=settings.TOOL_CONNECT_RETRY_DELAY,
            retries=settings.TOOL_CONNECT_RETRIES,
            enable_office=self.enable_office,
            enable_archive=self.enable_archive,
            enable_ocr=self.enable_ocr,
            archive_max_size_mb=settings.ARCHIVE_MAX_SIZE_MB,
        )
        self.tool_adapters = tool_adapters or ToolAdapterFactory.build_default_adapters(config)
        self.office_adapter = self.tool_adapters.get("office")
        self.archive_adapter = self.tool_adapters.get("archive")
        self.ocr_adapter = self.tool_adapters.get("ocr")

        # Extensions that need preprocessing
        self.office_extensions = {'.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt'}
        self.archive_extensions = {'.zip', '.7z', '.tar', '.tar.gz', '.tar.xz', '.tar.bz2', '.tgz'}
        self.ocr_extensions = {'.png', '.jpg', '.jpeg', '.tiff', '.bmp', '.pdf'}

        log.info(
            "FilePreprocessor initialized: office=%s, archive=%s, ocr=%s",
            self.enable_office, self.enable_archive, self.enable_ocr
        )

    def should_preprocess(self, file_path: Path) -> bool:
        """Check if a file needs preprocessing.

        Args:
            file_path: Path to file

        Returns:
            True if file needs preprocessing
        """
        suffix = file_path.suffix.lower()

        if self.office_adapter and self.office_adapter.enabled and suffix in self.office_extensions:
            return True

        if self.archive_adapter and self.archive_adapter.enabled and suffix in self.archive_extensions:
            return True

        if self.ocr_adapter and self.ocr_adapter.enabled and suffix in self.ocr_extensions:
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
            if self.office_adapter and suffix in self.office_extensions:
                return self._convert_office_document(file_path)

            if self.archive_adapter and suffix in self.archive_extensions:
                return self._extract_archive(file_path)

            if self.ocr_adapter and suffix in self.ocr_extensions:
                return self._perform_ocr(file_path)

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
        if not self.office_adapter:
            return file_path

        output = self.office_adapter.process(file_path)
        if output:
            return output

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
        if not self.archive_adapter:
            return None

        return self.archive_adapter.process(file_path)

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
        if not self.ocr_adapter:
            return None

        return self.ocr_adapter.process(file_path)

    def perform_ocr(self, file_path: Path) -> Optional[Path]:
        """Public wrapper to perform OCR on an image file."""
        return self._perform_ocr(file_path)

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

        for name, adapter in self.tool_adapters.items():
            status["tools_available"][name] = adapter.is_available()

        return status


# Singleton instance
_preprocessor_instance: Optional[FilePreprocessor] = None
_ingestion_preprocessor_instance: Optional[FilePreprocessor] = None


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


def get_ingestion_preprocessor(**kwargs) -> FilePreprocessor:
    """Get or create a preprocessor tailored for ingestion (no archive extraction)."""
    global _ingestion_preprocessor_instance
    if _ingestion_preprocessor_instance is None:
        _ingestion_preprocessor_instance = FilePreprocessor(enable_archive=False, **kwargs)
    return _ingestion_preprocessor_instance
