from pytest_readable import readable
#!/usr/bin/env python3
"""
Test script for OCR integration with PDF loader.

This script tests the automatic OCR processing for scanned PDFs.
"""

import sys
import tempfile
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from src.workflows.ingestion.loaders.pdf_loader import PDFLoader
from src.workflows.ingestion.preprocessor import get_preprocessor
from src.conf import settings

YELLOW = "\033[0;33m"
RESET = "\033[0m"

def print_warning(message: str) -> None:
    print(f"{YELLOW}⚠ {message}{RESET}")


@readable(
    intent="Test OCR integration for scanned PDFs.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the ocr integration behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_ocr_integration():
    """Test OCR integration for scanned PDFs."""
    print("[OCR Integration Test] Testing OCR Integration for Scanned PDFs")
    print("=" * 50)
    
    # Test 1: Check if OCR is enabled
    print("1. Checking OCR configuration...")
    print(f"   ENABLE_OCR: {settings.ENABLE_OCR}")
    print(f"   TOOL_OCR_URL: {settings.TOOL_OCR_URL}")
    
    if not settings.ENABLE_OCR:
        print("   ✗ OCR is disabled in settings")
        return False
    
    # Test 2: Check preprocessor configuration
    print("\n2. Checking preprocessor configuration...")
    preprocessor = get_preprocessor()
    status = preprocessor.get_status()
    
    print(f"   OCR enabled: {status['enabled']['ocr']}")
    print(f"   OCR tools available: {status['tools_available'].get('ocr', False)}")
    
    if not status['tools_available'].get('ocr'):
        print("   ✗ OCR tools not available")
        return False
    
    # Test 3: Check OCR extensions
    print("\n3. Checking OCR extensions...")
    print(f"   OCR extensions: {preprocessor.ocr_extensions}")
    
    if '.pdf' not in preprocessor.ocr_extensions:
        print("   ✗ PDF extension not in OCR extensions")
        return False
    
    # Test 4: Test PDF loader with OCR capability
    print("\n4. Testing PDF loader OCR integration...")
    
    # Create a test PDF file (we'll simulate a scanned PDF)
    test_pdf_path = Path(tempfile.gettempdir()) / "test_scanned.pdf"
    
    # For this test, we'll check if the PDF loader has the OCR method
    loader = PDFLoader(str(test_pdf_path))
    
    if hasattr(loader, '_try_ocr_for_scanned_pdf'):
        print("   ✓ PDF loader has OCR method")
    else:
        print("   ✗ PDF loader missing OCR method")
        return False
    
    # Test 5: Check OCR adapter
    print("\n5. Testing OCR adapter...")
    ocr_adapter = preprocessor.ocr_adapter
    
    if ocr_adapter and ocr_adapter.is_available():
        print("   ✓ OCR adapter is available")
    else:
        print("   ✗ OCR adapter not available")
        return False
    
    print("\n✓ All OCR integration tests passed!")
    return True


@readable(
    intent="Test document processor endpoints.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the document processor endpoints behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_document_processor_endpoints():
    """Test document processor endpoints."""
    print("\n[Document Processor Test] Testing Document Processor Endpoints")
    print("=" * 50)
    
    import requests
    
    # Test health check
    try:
        response = requests.get(f"{settings.TOOL_OCR_URL}/healthz", timeout=5)
        if response.status_code == 200:
            print("✓ Document processor health check passed")
            print(f"   Response: {response.json()}")
            return True
        else:
            print(f"✗ Health check failed: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"✗ Document processor not accessible: {e}")
        return False


def main():
    """Main test function."""
    print("[OCR Integration Test] Starting OCR Integration Tests")
    print("=" * 60)
    
    # Test OCR integration
    ocr_test_passed = test_ocr_integration()
    
    # Test document processor endpoints
    endpoint_test_passed = test_document_processor_endpoints()
    
    print("\n" + "=" * 60)
    print("[OCR Test Results] Test Results Summary:")
    print(f"   OCR Integration: {'✓ PASSED' if ocr_test_passed else '✗ FAILED'}")
    print(f"   Document Processor: {'✓ PASSED' if endpoint_test_passed else '✗ FAILED'}")
    
    if ocr_test_passed and endpoint_test_passed:
        print("\n[Integration Tests] All tests passed! OCR integration is working correctly.")
        return 0
    print()
    print_warning("Some tests failed. Please check the configuration.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
