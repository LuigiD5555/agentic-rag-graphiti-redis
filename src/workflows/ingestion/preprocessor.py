"""
File preprocessing using socket-activated tools.

This module handles automatic preprocessing of files that need conversion
before ingestion (Office docs, archives, images needing OCR, etc.).
"""

from pathlib import Path
from typing import Any, Dict, Optional

from src.conf import settings
from src.workflows.ingestion.tool_adapters import (
    ToolAdapter,
    ToolAdapterConfig,
    ToolAdapterFactory,
)
from src.workflows.query.audit import get_logger

log = get_logger(__name__)


class FilePreprocessor:
    """Preprocess files using socket-activated tools before ingestion.

    This component optionally converts Office documents, extracts archives,
    and runs OCR for images/scanned PDFs, using tool adapters.
    """

    def __init__(
        self,
        office_url: Optional[str] = None,
        archive_url: Optional[str] = None,
        ocr_url: Optional[str] = None,
        enable_office: bool = True,
        enable_archive: bool = True,
        enable_ocr: bool = False,
        timeout: int = 120,
        work_dir: Optional[str] = None,
        tool_adapters: Optional[Dict[str, ToolAdapter]] = None,
    ) -> None:
        """Initialize the preprocessor.

        Args:
            office_url: URL for Office conversion tool.
            archive_url: URL for archive extraction tool.
            ocr_url: URL for OCR tool.
            enable_office: Enable Office document conversion.
            enable_archive: Enable archive extraction.
            enable_ocr: Enable OCR for images/scanned PDFs (typically slower).
            timeout: Tool request timeout in seconds.
            work_dir: Working directory for processed files.
            tool_adapters: Optional injected adapters (testing/custom tooling).
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
        self.office_extensions = {".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt"}
        self.archive_extensions = {".zip", ".7z", ".tar", ".tar.gz", ".tar.xz", ".tar.bz2", ".tgz"}
        self.ocr_extensions = {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".pdf"}

        log.info(
            "FilePreprocessor initialized: office=%s, archive=%s, ocr=%s",
            self.enable_office,
            self.enable_archive,
            self.enable_ocr,
        )

    def should_preprocess(self, file_path: Path) -> bool:
        """Return True if the file should be preprocessed.

        This method also skips common temporary/lock files created by Office suites
        (e.g., PowerPoint/Word/Excel), which can be incomplete and may cause
        converters (LibreOffice) to hang or error.

        Args:
            file_path: Path to the file.

        Returns:
            True if preprocessing should be applied, otherwise False.
        """
        filename = file_path.name
        if filename.startswith(".~") or filename.startswith("~$"):
            return False

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
            file_path: Path to the input file.

        Returns:
            The processed file path, the original file path if no preprocessing is needed,
            or None if preprocessing failed.
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
        except Exception as exc:  # noqa: BLE001
            log.error("Preprocessing failed for %s: %s", file_path, exc)
            return None

    def _convert_office_document(self, file_path: Path) -> Optional[Path]:
        """Convert an Office document to text.

        Args:
            file_path: Path to an Office document.

        Returns:
            Path to the converted text file, or the original path if conversion is not possible,
            or None if a hard failure happens inside the tool adapter.
        """
        if not self.office_adapter:
            return file_path

        output = self.office_adapter.process(file_path)
        if output:
            return output

        # Try Python-based DOCX extraction as fallback when LibreOffice conversion fails.
        if file_path.suffix.lower() in {".docx", ".doc"}:
            python_extracted = self._try_python_docx_extraction(file_path)
            if python_extracted:
                return python_extracted

        log.info("Falling back to direct ingestion for %s", file_path.name)
        return file_path

    def convert_office_document(self, file_path: Path) -> Optional[Path]:
        """Public wrapper to convert an Office document to text.

        Args:
            file_path: Path to an Office document.

        Returns:
            Path to the converted text file, or the original path, or None if failed.
        """
        return self._convert_office_document(file_path)

    def _extract_archive(self, file_path: Path) -> Optional[Path]:
        """Extract an archive.

        Args:
            file_path: Path to an archive file.

        Returns:
            Path to the extraction directory, or None if extraction failed.
        """
        if not self.archive_adapter:
            return None

        return self.archive_adapter.process(file_path)

    def extract_archive(self, file_path: Path) -> Optional[Path]:
        """Public wrapper to extract an archive.

        Args:
            file_path: Path to an archive file.

        Returns:
            Path to the extraction directory, or None if failed.
        """
        return self._extract_archive(file_path)

    def _perform_ocr(self, file_path: Path) -> Optional[Path]:
        """Perform OCR on an image or PDF.

        Args:
            file_path: Path to an image file or a scanned PDF.

        Returns:
            Path to OCR-generated text file, or None if OCR is unavailable or failed.
        """
        if not self.ocr_adapter:
            return None

        return self.ocr_adapter.process(file_path)

    def perform_ocr(self, file_path: Path) -> Optional[Path]:
        """Public wrapper to perform OCR.

        Args:
            file_path: Path to an image file or PDF.

        Returns:
            Path to OCR-generated text file, or None if failed.
        """
        return self._perform_ocr(file_path)

    def _try_python_docx_extraction(self, file_path: Path) -> Optional[Path]:
        """Extract text from a DOCX file using python-docx as a fallback.

        This is used when LibreOffice conversion fails or returns empty output.

        Args:
            file_path: Path to a DOCX/DOC file.

        Returns:
            Path to an extracted text file, or None if extraction failed or produced no text.
        """
        try:
            import docx

            document = docx.Document(str(file_path))
            text_lines = []

            for paragraph in document.paragraphs:
                paragraph_text = paragraph.text.strip()
                if paragraph_text:
                    text_lines.append(paragraph_text)

            for table in document.tables:
                for row in table.rows:
                    for cell in row.cells:
                        cell_text = cell.text.strip()
                        if cell_text:
                            text_lines.append(cell_text)

            if not text_lines:
                log.warning("Python DOCX extraction produced no text for %s", file_path.name)
                return None

            output_path = self.work_dir / f"{file_path.stem}_python_fallback.txt"
            output_path.write_text("\n\n".join(text_lines), encoding="utf-8")
            log.info("Python DOCX extraction succeeded for %s -> %s", file_path.name, output_path.name)
            return output_path

        except ImportError:
            log.warning("python-docx not installed; cannot fallback for %s", file_path.name)
            return None
        except Exception as exc:  # noqa: BLE001
            log.warning("Python DOCX extraction failed for %s: %s", file_path.name, exc)
            return None

    def get_status(self) -> Dict[str, Any]:
        """Return preprocessor status and tool availability.

        Returns:
            A dict containing feature flags and availability of tool adapters.
        """
        status: Dict[str, Any] = {
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


_preprocessor_instance: Optional[FilePreprocessor] = None
_ingestion_preprocessor_instance: Optional[FilePreprocessor] = None


def get_preprocessor(**kwargs: Any) -> FilePreprocessor:
    """Get or create the FilePreprocessor singleton.

    Args:
        **kwargs: Arguments forwarded to FilePreprocessor constructor.

    Returns:
        The singleton FilePreprocessor instance.
    """
    global _preprocessor_instance
    if _preprocessor_instance is None:
        _preprocessor_instance = FilePreprocessor(**kwargs)
    return _preprocessor_instance


def get_ingestion_preprocessor(**kwargs: Any) -> FilePreprocessor:
    """Get or create a FilePreprocessor tailored for ingestion (no archive extraction).

    Args:
        **kwargs: Arguments forwarded to FilePreprocessor constructor.

    Returns:
        The singleton FilePreprocessor instance configured for ingestion.
    """
    global _ingestion_preprocessor_instance
    if _ingestion_preprocessor_instance is None:
        _ingestion_preprocessor_instance = FilePreprocessor(enable_archive=False, **kwargs)
    return _ingestion_preprocessor_instance
