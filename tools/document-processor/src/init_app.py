"""
Application initialization with all improvements integrated.
"""

import os
import sys
from pathlib import Path

# Add current directory to Python path
sys.path.insert(0, str(Path(__file__).parent))


def initialize_application():
    """
    Initialize the document processing application with all improvements.
    """
    print("Initializing document processor with improvements...")
    
    # 1. Suppress openpyxl warnings
    try:
        from .openpyxl_warnings import suppress_openpyxl_warnings
        suppress_openpyxl_warnings()
        print("✓ Suppressed openpyxl warnings")
    except ImportError as e:
        print(f"✗ Could not suppress openpyxl warnings: {e}")
    
    # 2. Setup temporary directory
    try:
        from .temp_file_manager import setup_temp_directory
        work_dir = os.getenv("WORK_DIR", "/tmp/rag-work")
        work_path = setup_temp_directory(work_dir)
        print(f"✓ Setup temporary directory: {work_path}")
    except Exception as e:
        print(f"✗ Could not setup temporary directory: {e}")
    
    # 3. Optimize memory usage
    try:
        from .memory_config import optimize_memory_usage
        optimize_memory_usage()
        print("✓ Optimized memory configuration")
    except Exception as e:
        print(f"✗ Could not optimize memory: {e}")
    
    # 4. Check system resources
    try:
        from .memory_config import check_memory_available
        if check_memory_available(min_memory_gb=1.0):
            print("✓ Sufficient memory available")
        else:
            print("⚠ Low memory warning")
    except Exception as e:
        print(f"✗ Could not check memory: {e}")
    
    print("Application initialization complete!")
    return True


def validate_document_file(file_path: str) -> tuple:
    """
    Validate a document file before processing.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Tuple of (is_valid, message)
    """
    try:
        from .document_validator import validate_document_file as validate_file
        from .document_validator import is_scanned_pdf
        
        path = Path(file_path)
        
        # Basic validation
        is_valid, message = validate_file(path)
        if not is_valid:
            return False, message
        
        # Check for scanned PDFs
        if path.suffix.lower() == '.pdf':
            is_scanned, scan_message = is_scanned_pdf(path)
            if is_scanned:
                return False, f"Scanned PDF detected: {scan_message}. Enable OCR for processing."
        
        return True, "File is valid for processing"
        
    except Exception as e:
        return False, f"Validation error: {str(e)}"


def get_document_metadata(file_path: str) -> dict:
    """
    Get metadata for a document file.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Dictionary with metadata
    """
    try:
        from .document_validator import get_file_metadata
        path = Path(file_path)
        return get_file_metadata(path)
    except Exception:
        return {}


class DocumentProcessorConfig:
    """
    Configuration for document processing.
    """
    
    def __init__(self):
        self.max_file_size_mb = 100
        self.enable_ocr = True
        self.ocr_language = "eng"
        self.enable_validation = True
        self.temp_dir = "/tmp/rag-work"
        self.concurrent_limit = 3
        
    def update_from_env(self):
        """Update configuration from environment variables."""
        # Max file size
        max_size = os.getenv("MAX_FILE_SIZE_MB")
        if max_size:
            try:
                self.max_file_size_mb = int(max_size)
            except ValueError:
                pass
        
        # OCR settings
        self.enable_ocr = os.getenv("ENABLE_OCR", "true").lower() == "true"
        self.ocr_language = os.getenv("OCR_LANGUAGE", "eng")
        
        # Temp directory
        temp_dir = os.getenv("WORK_DIR")
        if temp_dir:
            self.temp_dir = temp_dir
        
        # Concurrent limit
        concurrent = os.getenv("CONCURRENT_PROCESSES")
        if concurrent:
            try:
                self.concurrent_limit = int(concurrent)
            except ValueError:
                pass
    
    def to_dict(self) -> dict:
        """Convert configuration to dictionary."""
        return {
            'max_file_size_mb': self.max_file_size_mb,
            'enable_ocr': self.enable_ocr,
            'ocr_language': self.ocr_language,
            'enable_validation': self.enable_validation,
            'temp_dir': self.temp_dir,
            'concurrent_limit': self.concurrent_limit,
        }


# Global configuration instance
_config = DocumentProcessorConfig()


def get_config() -> DocumentProcessorConfig:
    """
    Get the global configuration instance.
    
    Returns:
        DocumentProcessorConfig instance
    """
    return _config


if __name__ == "__main__":
    # Test initialization
    success = initialize_application()
    if success:
        print("\nConfiguration:")
        config = get_config()
        config.update_from_env()
        for key, value in config.to_dict().items():
            print(f"  {key}: {value}")
    else:
        print("Initialization failed")
