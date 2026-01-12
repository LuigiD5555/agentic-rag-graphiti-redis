"""Example client for RAG tools.

This demonstrates how to integrate the socket-activated tools
into your RAG ingestion pipeline.
"""
import os
from pathlib import Path
from typing import Optional, Literal
import requests


class ToolClient:
    """Client for RAG processing tools."""

    def __init__(
        self,
        office_url: str = "http://127.0.0.1:9106",
        archive_url: str = "http://127.0.0.1:9101",
        ocr_url: str = "http://127.0.0.1:9103",
        timeout: int = 120,
    ):
        """Initialize tool client.

        Args:
            office_url: Document processor (office conversion) tool URL
            archive_url: Archive extraction tool URL
            ocr_url: OCR tool URL
            timeout: Default request timeout (seconds)
        """
        self.office_url = office_url
        self.archive_url = archive_url
        self.ocr_url = ocr_url
        self.timeout = timeout

    def convert_office_document(
        self,
        input_path: str,
        output_format: Literal["pdf", "txt", "md"] = "pdf",
        output_path: Optional[str] = None,
    ) -> dict:
        """Convert Office document to PDF/text/markdown.

        Args:
            input_path: Path to input file (DOCX, XLSX, PPTX)
            output_format: Output format (pdf, txt, md)
            output_path: Optional output path

        Returns:
            Response dict with success, output_path, error fields
        """
        response = requests.post(
            f"{self.office_url}/convert",
            json={
                "input_path": input_path,
                "output_format": output_format,
                "output_path": output_path,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def extract_archive(
        self,
        archive_path: str,
        output_dir: Optional[str] = None,
        max_size_mb: int = 500,
    ) -> dict:
        """Extract archive (ZIP, 7z, tar, etc.).

        Args:
            archive_path: Path to archive file
            output_dir: Optional output directory
            max_size_mb: Maximum extracted size in MB (safety limit)

        Returns:
            Response dict with success, output_dir, extracted_files, error fields
        """
        response = requests.post(
            f"{self.archive_url}/extract",
            json={
                "archive_path": archive_path,
                "output_dir": output_dir,
                "max_size_mb": max_size_mb,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def list_archive_contents(self, archive_path: str) -> dict:
        """List contents of an archive without extracting.

        Args:
            archive_path: Path to archive file

        Returns:
            Response dict with success, files, file_count, error fields
        """
        response = requests.post(
            f"{self.archive_url}/list",
            json={"archive_path": archive_path},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def perform_ocr(
        self,
        input_path: str,
        language: str = "eng",
        output_format: Literal["txt", "hocr", "pdf"] = "txt",
        output_path: Optional[str] = None,
        psm: int = 3,
    ) -> dict:
        """Perform OCR on image or PDF.

        Args:
            input_path: Path to input file (image or PDF)
            language: Tesseract language code (eng, spa, fra, etc.)
            output_format: Output format (txt, hocr, pdf)
            output_path: Optional output path
            psm: Page segmentation mode (0-13)

        Returns:
            Response dict with success, output_path, text, error fields
        """
        response = requests.post(
            f"{self.ocr_url}/ocr",
            json={
                "input_path": input_path,
                "language": language,
                "output_format": output_format,
                "output_path": output_path,
                "psm": psm,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def pdf_to_images(
        self,
        pdf_path: str,
        output_dir: Optional[str] = None,
        dpi: int = 300,
        format: Literal["png", "jpg"] = "png",
    ) -> dict:
        """Convert PDF pages to images.

        Args:
            pdf_path: Path to PDF file
            output_dir: Optional output directory
            dpi: Resolution in DPI
            format: Image format (png, jpg)

        Returns:
            Response dict with success, output_dir, image_paths, page_count, error
        """
        response = requests.post(
            f"{self.ocr_url}/pdf-to-images",
            json={
                "pdf_path": pdf_path,
                "output_dir": output_dir,
                "dpi": dpi,
                "format": format,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()


# Example usage in ingestion pipeline
def process_document(file_path: Path, tool_client: ToolClient) -> Optional[str]:
    """Process a document based on its type.

    Args:
        file_path: Path to document
        tool_client: Initialized ToolClient

    Returns:
        Path to processed text file, or None if processing failed
    """
    suffix = file_path.suffix.lower()

    try:
        # Office documents -> convert to PDF, then to text
        if suffix in [".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt"]:
            print(f"Converting Office document: {file_path}")
            result = tool_client.convert_office_document(
                str(file_path),
                output_format="txt"
            )
            if result["success"]:
                return result["output_path"]
            else:
                print(f"Conversion failed: {result.get('error')}")
                return None

        # Archives -> extract first
        elif suffix in [".zip", ".7z", ".tar", ".tar.gz", ".tgz"]:
            print(f"Extracting archive: {file_path}")
            result = tool_client.extract_archive(str(file_path))
            if result["success"]:
                # Process extracted files recursively
                print(f"Extracted {result['file_count']} files to {result['output_dir']}")
                # You would recursively process the extracted files here
                return result["output_dir"]
            else:
                print(f"Extraction failed: {result.get('error')}")
                return None

        # Images/scanned PDFs -> OCR
        elif suffix in [".png", ".jpg", ".jpeg", ".tiff", ".bmp"]:
            print(f"Performing OCR on image: {file_path}")
            result = tool_client.perform_ocr(str(file_path))
            if result["success"]:
                return result["output_path"]
            else:
                print(f"OCR failed: {result.get('error')}")
                return None

        # PDFs -> might need OCR
        elif suffix == ".pdf":
            # Try OCR (in production, check if PDF has text first)
            print(f"Performing OCR on PDF: {file_path}")
            result = tool_client.perform_ocr(str(file_path))
            if result["success"]:
                return result["output_path"]
            else:
                print(f"OCR failed: {result.get('error')}")
                return None

        else:
            print(f"Unsupported file type: {suffix}")
            return None

    except requests.RequestException as e:
        print(f"Tool request failed: {e}")
        return None


if __name__ == "__main__":
    # Example: process a document
    client = ToolClient()

    # Example: convert a Word document
    result = client.convert_office_document(
        "/mnt/documents/example.docx",
        output_format="pdf"
    )
    print(f"Conversion result: {result}")

    # Example: extract an archive
    result = client.extract_archive(
        "/mnt/documents/data.zip",
        max_size_mb=100
    )
    print(f"Extraction result: {result}")

    # Example: OCR a scanned document
    result = client.perform_ocr(
        "/mnt/documents/scan.pdf",
        language="eng"
    )
    print(f"OCR result: {result}")
