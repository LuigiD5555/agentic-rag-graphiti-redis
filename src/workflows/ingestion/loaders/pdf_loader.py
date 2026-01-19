from typing import List, Optional
import hashlib
import json
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from io import BytesIO

from pypdf import PdfReader
from pypdf.errors import PdfReadError, PdfStreamError

from langchain_core.documents import Document

from src.workflows.ingestion.loaders.errors import LoaderInvalidFormatError, ensure_file_exists
from src.workflows.ingestion.preprocessor import get_preprocessor
from src import logger


class PDFLoader:
    """
    PDF document loader with optional content caching, timeout, and incremental loading.

    This loader can cache extracted PDF text in Redis to avoid expensive
    re-extraction on subsequent runs. The cache key is based on file path
    and modification time.

    Features:
    - Redis caching for extracted content
    - Timeout protection for large/complex PDFs
    - Incremental page loading for very large PDFs (reduces memory pressure)
    - Detection of scanned PDFs (image-based, no extractable text)
    """

    # PDF size thresholds
    LARGE_PDF_THRESHOLD = 50 * 1024 * 1024   # 50 MB - use incremental loading
    MAX_PDF_SIZE_BYTES = 500 * 1024 * 1024   # 500 MB - absolute maximum (increased from 200 MB)

    # Incremental loading settings
    PAGES_PER_BATCH = 50                     # Process 50 pages at a time for large PDFs

    # Timeout for PDF loading in seconds (5 minutes per batch)
    LOAD_TIMEOUT_SECONDS = 300

    def __init__(
        self,
        path: str,
        redis_client: Optional[any] = None,
        cache_ttl: int = 2592000,
        load_timeout: Optional[int] = None
    ):
        """
        Initialize PDF loader with optional Redis cache.

        Args:
            path: Path to PDF file
            redis_client: Optional Redis client for caching extracted content
            cache_ttl: Cache TTL in seconds (default: 30 days)
            load_timeout: Timeout in seconds for PDF loading (default: 300s)
        """
        self._path = path
        self.redis_client = redis_client
        self.cache_ttl = cache_ttl
        self.cache_enabled = (
            redis_client is not None
            and os.environ.get("RAG_PDF_CACHE_ENABLED", "true").lower()
            in ("true", "1", "yes")
        )
        self.load_timeout = load_timeout or self.LOAD_TIMEOUT_SECONDS

    def _compute_cache_key(self) -> str:
        """
        Compute cache key based on file path and mtime.

        This ensures cache invalidation when file changes.
        """
        try:
            stat = Path(self._path).stat()
            # Include path and mtime in key
            key_base = f"{self._path}::{stat.st_mtime}::{stat.st_size}"
            key_hash = hashlib.sha256(key_base.encode("utf-8")).hexdigest()
            return f"pdf_content:{key_hash}"
        except Exception as e:
            logger.debug("Failed to compute PDF cache key: %s", e)
            return None

    def _get_from_cache(self, cache_key: str) -> Optional[List[Document]]:
        """Retrieve cached PDF content."""
        if not self.cache_enabled or not cache_key:
            return None

        try:
            cached_data = self.redis_client.get(cache_key)
            if cached_data is None:
                return None

            # Deserialize documents
            doc_dicts = json.loads(cached_data)
            documents = [
                Document(page_content=d["page_content"], metadata=d["metadata"])
                for d in doc_dicts
            ]
            logger.info(
                "PDF CACHE HIT: Loaded %d pages from cache for %s",
                len(documents),
                Path(self._path).name
            )
            return documents

        except Exception as e:
            logger.debug("PDF cache retrieval error: %s", e)
            return None

    def _store_in_cache(
        self, cache_key: str, documents: List[Document]
    ) -> None:
        """Store extracted PDF content in cache."""
        if not self.cache_enabled or not cache_key:
            return

        try:
            # Serialize documents
            doc_dicts = [
                {"page_content": doc.page_content, "metadata": doc.metadata}
                for doc in documents
            ]
            cached_data = json.dumps(doc_dicts)
            self.redis_client.setex(cache_key, self.cache_ttl, cached_data)
            logger.info(
                "PDF CACHE STORE: Cached %d pages for %s (ttl=%ds)",
                len(documents),
                Path(self._path).name,
                self.cache_ttl
            )
        except Exception as e:
            logger.debug("PDF cache storage error: %s", e)

    def _is_scanned_pdf(self, documents: List[Document]) -> bool:
        """
        Detect if PDF is scanned (image-based with little extractable text).

        Args:
            documents: List of extracted documents

        Returns:
            True if the PDF appears to be scanned images, False otherwise
        """
        if not documents:
            return True

        total_text = sum(len(doc.page_content.strip()) for doc in documents)
        avg_chars_per_page = total_text / len(documents) if documents else 0

        # If average is less than 100 chars per page, likely scanned
        if avg_chars_per_page < 100:
            logger.warning(
                "PDF appears to be scanned images (avg %.1f chars/page): %s",
                avg_chars_per_page,
                Path(self._path).name
            )
            return True

        return False

    def _load_incrementally(self, file_size: float) -> List[Document]:
        """
        Load large PDF incrementally by batches of pages to reduce memory pressure.

        Args:
            file_size: Size of the PDF file in bytes

        Returns:
            List of Document objects (one per page)
        """
        logger.info(
            "Loading large PDF incrementally (%.1f MB): %s",
            file_size / (1024 * 1024),
            Path(self._path).name
        )

        all_documents = []

        try:
            # Temporarily suppress pypdf logging warnings
            import logging
            pypdf_logger = logging.getLogger('pypdf._reader')
            original_level = pypdf_logger.level
            pypdf_logger.setLevel(logging.ERROR)
            
            try:
                reader = PdfReader(self._path, strict=False)
            except (AttributeError, UnboundLocalError) as e:
                # Handle specific case where encryption_entry is NullObject
                if "'NullObject' object has no attribute 'get'" in str(e):
                    logger.warning(
                        "PDF has malformed encryption dictionary (NullObject), attempting workaround: %s",
                        Path(self._path).name
                    )
                    # Try alternative approach: read PDF as binary and create reader
                    with open(self._path, 'rb') as f:
                        pdf_bytes = f.read()
                    
                    # Create reader from bytes using BytesIO
                    reader = PdfReader(BytesIO(pdf_bytes), strict=False)
                    
                    # Try to bypass encryption by setting it to None if it exists
                    if hasattr(reader, '_encryption') and reader._encryption is not None:
                        logger.debug("Bypassing encryption for malformed PDF")
                        reader._encryption = None
                else:
                    # Handle UnboundLocalError specifically
                    if isinstance(e, UnboundLocalError):
                        logger.error(
                            "PDF loader error: PdfReader not available in scope for %s. "
                            "This may indicate a problem with pypdf installation or imports.",
                            Path(self._path).name
                        )
                        raise LoaderInvalidFormatError(
                            self._path,
                            expected="PDF",
                            detail=f"PDF loader configuration error: {str(e)}. "
                                   "Check that pypdf is properly installed and imported."
                        ) from e
                    # Re-raise other AttributeErrors
                    raise
            finally:
                # Restore original logging level
                pypdf_logger.setLevel(original_level)
            
            total_pages = len(reader.pages)

            logger.info(
                "PDF has %d pages, processing in batches of %d",
                total_pages,
                self.PAGES_PER_BATCH
            )

            # Process in batches
            for batch_start in range(0, total_pages, self.PAGES_PER_BATCH):
                batch_end = min(batch_start + self.PAGES_PER_BATCH, total_pages)
                batch_num = (batch_start // self.PAGES_PER_BATCH) + 1
                total_batches = (total_pages + self.PAGES_PER_BATCH - 1) // self.PAGES_PER_BATCH

                logger.info(
                    "Processing batch %d/%d (pages %d-%d of %d)",
                    batch_num,
                    total_batches,
                    batch_start + 1,
                    batch_end,
                    total_pages
                )

                # Extract text from pages in this batch
                for page_num in range(batch_start, batch_end):
                    try:
                        page = reader.pages[page_num]
                        text = page.extract_text()

                        # Create document for this page
                        doc = Document(
                            page_content=text or "",
                            metadata={
                                "source": self._path,
                                "page": page_num,
                                "total_pages": total_pages,
                            }
                        )
                        all_documents.append(doc)

                    except Exception as e:
                        logger.warning(
                            "Failed to extract page %d: %s",
                            page_num + 1,
                            str(e)
                        )
                        # Continue with next page instead of failing entirely
                        continue

                # Log progress
                progress_pct = (batch_end / total_pages) * 100
                logger.info(
                    "Progress: %d/%d pages (%.1f%%)",
                    batch_end,
                    total_pages,
                    progress_pct
                )

            logger.info(
                "Completed incremental loading: %d pages extracted from %s",
                len(all_documents),
                Path(self._path).name
            )

            return all_documents

        except Exception as exc:
            raise LoaderInvalidFormatError(
                self._path,
                expected="PDF",
                detail=f"Incremental loading failed: {str(exc)}"
            ) from exc

    def _load_with_timeout(self) -> List[Document]:
        """
        Load PDF with timeout protection.

        Returns:
            List of documents extracted from PDF

        Raises:
            TimeoutError: If loading takes longer than configured timeout
            LoaderInvalidFormatError: If PDF is corrupted or invalid
        """
        def _do_load():
            return self._load_normally()

        # Try to use ThreadPoolExecutor for timeout, but handle shutdown gracefully
        try:
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_do_load)
                try:
                    documents = future.result(timeout=self.load_timeout)
                    return documents
                except FuturesTimeoutError as exc:
                    logger.error(
                        "PDF load timeout after %ds: %s (%.1f MB)",
                        self.load_timeout,
                        Path(self._path).name,
                        os.path.getsize(self._path) / (1024 * 1024)
                    )
                    raise TimeoutError(
                        f"PDF loading exceeded {self.load_timeout}s timeout"
                    ) from exc
        except RuntimeError as exc:
            # Handle "cannot schedule new futures after interpreter shutdown"
            if "cannot schedule new futures" in str(exc):
                logger.warning(
                    "PDF loader cannot use timeout during interpreter shutdown, "
                    "loading without timeout: %s",
                    Path(self._path).name
                )
                # Fall back to loading without timeout during shutdown
                return _do_load()
            else:
                # Re-raise other RuntimeErrors
                raise

    def _load_normally(self) -> List[Document]:
        """
        Load every page of the PDF with a permissive reader.

        Returns:
            List of Document objects extracted from the PDF pages.
        """
        logger.debug("Loading PDF using pypdf with strict=False fallback: %s", Path(self._path).name)
        
        # Temporarily suppress pypdf logging warnings
        import logging
        pypdf_logger = logging.getLogger('pypdf._reader')
        original_level = pypdf_logger.level
        pypdf_logger.setLevel(logging.ERROR)
        
        try:
            reader = PdfReader(self._path, strict=False)
        except (AttributeError, UnboundLocalError) as e:
            # Handle specific case where encryption_entry is NullObject
            if "'NullObject' object has no attribute 'get'" in str(e):
                logger.warning(
                    "PDF has malformed encryption dictionary (NullObject), attempting workaround: %s",
                    Path(self._path).name
                )
                # Try alternative approach: read PDF as binary and create reader
                try:
                    # Read file as binary and create PdfReader from bytes
                    with open(self._path, 'rb') as f:
                        pdf_bytes = f.read()
                    
                    # Create reader from bytes using BytesIO
                    reader = PdfReader(BytesIO(pdf_bytes), strict=False)
                    
                    # Try to bypass encryption by setting it to None if it exists
                    if hasattr(reader, '_encryption') and reader._encryption is not None:
                        logger.debug("Bypassing encryption for malformed PDF")
                        reader._encryption = None
                        
                except Exception as inner_e:
                    logger.error(
                        "Failed to work around malformed encryption for PDF %s: %s",
                        Path(self._path).name, str(inner_e)
                    )
                    raise LoaderInvalidFormatError(
                        self._path,
                        expected="PDF",
                        detail=f"PDF has malformed encryption that cannot be processed: {str(inner_e)}"
                    ) from inner_e
            else:
                # Handle UnboundLocalError specifically
                if isinstance(e, UnboundLocalError):
                    logger.error(
                        "PDF loader error: PdfReader not available in scope for %s. "
                        "This may indicate a problem with pypdf installation or imports.",
                        Path(self._path).name
                    )
                    raise LoaderInvalidFormatError(
                        self._path,
                        expected="PDF",
                        detail=f"PDF loader configuration error: {str(e)}. "
                               "Check that pypdf is properly installed and imported."
                    ) from e
                # Re-raise other AttributeErrors
                raise
        finally:
            # Restore original logging level
            pypdf_logger.setLevel(original_level)
        
        documents: List[Document] = []
        total_pages = len(reader.pages)

        for page_num in range(total_pages):
            try:
                page = reader.pages[page_num]
                text = page.extract_text()
                documents.append(
                    Document(
                        page_content=text or "",
                        metadata={
                            "source": self._path,
                            "page": page_num,
                            "total_pages": total_pages,
                        },
                    )
                )
            except Exception as exc:
                logger.warning(
                    "Failed to extract page %d during normal load: %s",
                    page_num + 1,
                    str(exc)
                )
                continue

        logger.info(
            "Completed normal loading: %d/%d pages extracted from %s",
            len(documents),
            total_pages,
            Path(self._path).name
        )
        return documents

    def load(self) -> List[Document]:
        """
        Load PDF documents with caching, timeout, size limits, and incremental loading.

        For PDFs larger than LARGE_PDF_THRESHOLD (50 MB), uses incremental loading
        to process pages in batches, reducing memory pressure.

        Returns:
            List[Document]: Extracted documents from PDF

        Raises:
            LoaderInvalidFormatError: If PDF is invalid, too large, or scanned
            TimeoutError: If loading exceeds timeout
        """
        ensure_file_exists(self._path)

        # Check file size before attempting to load
        file_size = os.path.getsize(self._path)
        if file_size > self.MAX_PDF_SIZE_BYTES:
            logger.warning(
                "Skipping oversized PDF: %s (%.1f MB > %.1f MB limit)",
                Path(self._path).name,
                file_size / (1024 * 1024),
                self.MAX_PDF_SIZE_BYTES / (1024 * 1024)
            )
            raise LoaderInvalidFormatError(
                self._path,
                expected="PDF",
                detail=f"File size {file_size / (1024 * 1024):.1f} MB "
                       f"exceeds limit of {self.MAX_PDF_SIZE_BYTES / (1024 * 1024):.1f} MB"
            )

        # Try cache first
        cache_key = self._compute_cache_key()
        if cache_key:
            cached_docs = self._get_from_cache(cache_key)
            if cached_docs is not None:
                return cached_docs

        # Cache miss - extract from PDF
        try:
            logger.debug("Extracting PDF content from %s", Path(self._path).name)

            # Decide loading strategy based on file size
            if file_size > self.LARGE_PDF_THRESHOLD:
                # Use incremental loading for large PDFs
                documents = self._load_incrementally(file_size)
            else:
                # Use standard loading with timeout for smaller PDFs
                documents = self._load_with_timeout()

            # Check if PDF is scanned (image-based)
            if self._is_scanned_pdf(documents):
                # Try OCR for scanned PDFs
                logger.info("PDF appears to be scanned, attempting OCR: %s", Path(self._path).name)
                ocr_documents = self._try_ocr_for_scanned_pdf()
                if ocr_documents:
                    logger.info("OCR successful for scanned PDF: %s", Path(self._path).name)
                    # Store OCR result in cache
                    if cache_key:
                        self._store_in_cache(cache_key, ocr_documents)
                    return ocr_documents
                else:
                    # OCR failed or not available, raise error
                    raise LoaderInvalidFormatError(
                        self._path,
                        expected="PDF with extractable text",
                        detail="PDF appears to be scanned images with no extractable text and OCR failed or not available"
                    )

            # Store in cache for future use
            if cache_key:
                self._store_in_cache(cache_key, documents)

            return documents

        except TimeoutError:
            # Re-raise timeout errors
            raise

        except (PdfReadError, PdfStreamError, ValueError) as exc:
            raise LoaderInvalidFormatError(
                self._path,
                expected="PDF",
                detail=str(exc),
            ) from exc

    def _try_ocr_for_scanned_pdf(self) -> Optional[List[Document]]:
        """
        Attempt OCR on scanned PDF using the document processor service.

        Returns:
            List of Document objects from OCR, or None if OCR failed or not available
        """
        try:
            # Get preprocessor instance
            preprocessor = get_preprocessor()
            
            # Check if OCR adapter is available
            ocr_adapter = preprocessor.ocr_adapter
            if not ocr_adapter or not ocr_adapter.is_available():
                logger.warning("OCR adapter not available for scanned PDF: %s", Path(self._path).name)
                return None
            
            # Perform OCR on the PDF
            ocr_result_path = ocr_adapter.process(Path(self._path))
            if not ocr_result_path or not ocr_result_path.exists():
                logger.warning("OCR failed for scanned PDF: %s", Path(self._path).name)
                return None
            
            # Read OCR result and convert to Document objects
            with open(ocr_result_path, 'r', encoding='utf-8') as f:
                ocr_text = f.read()
            
            if not ocr_text.strip():
                logger.warning("OCR produced empty text for scanned PDF: %s", Path(self._path).name)
                return None
            
            # Create a single document with the OCR text
            # For multi-page PDFs, the OCR service should handle page separation
            document = Document(
                page_content=ocr_text,
                metadata={
                    "source": self._path,
                    "page": 0,
                    "total_pages": 1,
                    "ocr_processed": True,
                    "scanned_pdf": True,
                }
            )
            
            logger.info("OCR successful for scanned PDF: %s (%d characters extracted)", 
                       Path(self._path).name, len(ocr_text))
            
            return [document]
            
        except Exception as e:
            logger.error("Error during OCR processing for scanned PDF %s: %s", 
                        Path(self._path).name, str(e))
            return None
