#!/usr/bin/env python3
"""Test script to verify PDF loader fix."""

import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.workflows.ingestion.loaders.pdf_loader import PDFLoader

def test_pdf_loader():
    """Test PDF loader with a sample PDF."""
    # Find a test PDF in the resources
    test_pdf_path = None
    
    # Try to find a PDF in the resources directory
    resources_dir = Path("/mnt/resources/Libros/Aprendizaje/Matemáticas/MEGA")
    if resources_dir.exists():
        pdf_files = list(resources_dir.glob("*.pdf"))
        if pdf_files:
            test_pdf_path = str(pdf_files[0])
            print(f"Found test PDF: {test_pdf_path}")
        else:
            print("No PDF files found in resources directory")
            return False
    else:
        print("Resources directory not found, creating a simple test...")
        # Create a simple test with a non-existent PDF to test error handling
        test_pdf_path = "/tmp/test_nonexistent.pdf"
    
    try:
        # Create PDF loader instance
        loader = PDFLoader(test_pdf_path)
        
        # Try to load the PDF
        print(f"Attempting to load PDF: {test_pdf_path}")
        documents = loader.load()
        
        if documents:
            print(f"SUCCESS: Loaded {len(documents)} documents from PDF")
            for i, doc in enumerate(documents[:3]):  # Show first 3
                print(f"  Document {i+1}: {len(doc.page_content)} characters")
                if doc.metadata:
                    print(f"    Metadata: {doc.metadata}")
            return True
        else:
            print("WARNING: No documents loaded (empty PDF or error)")
            return False
            
    except Exception as e:
        print(f"ERROR: Failed to load PDF: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_pdf_loader_error_handling():
    """Test PDF loader error handling."""
    print("\nTesting error handling...")
    
    # Test with non-existent file
    try:
        loader = PDFLoader("/tmp/nonexistent_file.pdf")
        documents = loader.load()
        print("ERROR: Should have raised an exception for non-existent file")
        return False
    except Exception as e:
        print(f"SUCCESS: Correctly raised exception for non-existent file: {type(e).__name__}")
    
    # Test with invalid file (text file instead of PDF)
    test_txt = "/tmp/test.txt"
    with open(test_txt, "w") as f:
        f.write("This is not a PDF file")
    
    try:
        loader = PDFLoader(test_txt)
        documents = loader.load()
        print("ERROR: Should have raised an exception for invalid PDF")
        return False
    except Exception as e:
        print(f"SUCCESS: Correctly raised exception for invalid PDF: {type(e).__name__}")
    
    os.remove(test_txt)
    return True

if __name__ == "__main__":
    print("Testing PDF loader fix...")
    
    success = test_pdf_loader()
    
    if success:
        print("\nPDF loader test PASSED!")
    else:
        print("\nPDF loader test FAILED!")
        sys.exit(1)
