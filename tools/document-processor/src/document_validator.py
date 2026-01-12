"""
Document validation and preprocessing utilities.
"""

import os
from pathlib import Path
from typing import Optional, Tuple


def validate_document_file(file_path: Path) -> Tuple[bool, Optional[str]]:
    """
    Validate if a document file is readable and not corrupted.
    
    Args:
        file_path: Path to the file to validate
        
    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check if file exists
    if not file_path.exists():
        return False, f"File not found: {file_path}"
    
    # Check if it's a file
    if not file_path.is_file():
        return False, f"Path is not a file: {file_path}"
    
    # Check file size
    try:
        file_size = file_path.stat().st_size
        if file_size == 0:
            return False, f"File is empty: {file_path}"
        if file_size > 100 * 1024 * 1024:  # 100MB limit
            return False, f"File too large ({file_size / (1024*1024):.1f}MB): {file_path}"
    except OSError as e:
        return False, f"Cannot access file: {e}"
    
    # Check file permissions
    if not os.access(file_path, os.R_OK):
        return False, f"File not readable (permission denied): {file_path}"
    
    # Try to detect file type using python-magic
    try:
        import magic as magic_lib
        mime = magic_lib.from_file(str(file_path), mime=True)
        
        # Check for known problematic file types
        if mime in ['application/x-msdownload', 'application/x-dosexec']:
            return False, f"File appears to be executable, not a document: {file_path}"
        
        # Check for encrypted/compressed files
        if mime in ['application/x-7z-compressed', 'application/x-rar-compressed']:
            return False, f"File is compressed archive, not a document: {file_path}"
            
    except ImportError:
        # python-magic not available, skip MIME detection
        pass
    except Exception:
        # MIME detection failed, continue without it
        pass
    
    return True, None


def is_scanned_pdf(file_path: Path) -> Tuple[bool, Optional[str]]:
    """
    Check if a PDF file appears to be scanned images without extractable text.
    
    Args:
        file_path: Path to PDF file
        
    Returns:
        Tuple of (is_scanned, error_message)
    """
    if file_path.suffix.lower() != '.pdf':
        return False, "Not a PDF file"
    
    try:
        # Try to extract text using pdftotext
        import subprocess
        import tempfile
        
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as tmp:
            tmp_path = tmp.name
        
        try:
            result = subprocess.run(
                ['pdftotext', str(file_path), tmp_path],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode != 0:
                return True, f"pdftotext failed with code {result.returncode}"
            
            # Check if output file has content
            if os.path.exists(tmp_path):
                with open(tmp_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                
                # Count characters
                char_count = len(content.strip())
                
                if char_count == 0:
                    return True, "PDF appears to be scanned images (0 characters extracted)"
                elif char_count < 100:  # Very little text
                    return True, f"PDF appears to be scanned images ({char_count} characters extracted)"
                else:
                    return False, None
            else:
                return True, "pdftotext produced no output"
                
        finally:
            # Clean up temp file
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
                
    except subprocess.TimeoutExpired:
        return True, "PDF text extraction timed out (likely complex/scanned)"
    except Exception as e:
        return True, f"Error checking PDF: {str(e)}"


def get_file_metadata(file_path: Path) -> dict:
    """
    Get metadata about a file.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Dictionary with file metadata
    """
    try:
        stat = file_path.stat()
        return {
            'size_bytes': stat.st_size,
            'modified_at': stat.st_mtime,
            'created_at': stat.st_ctime,
            'is_readable': os.access(file_path, os.R_OK),
            'is_writable': os.access(file_path, os.W_OK),
            'extension': file_path.suffix.lower(),
        }
    except OSError:
        return {}
