from pytest_readable import readable
#!/usr/bin/env python3
"""
Test script to verify all improvements are working correctly.
"""

import sys
import os
from pathlib import Path

# Add tools directory to path
sys.path.insert(0, str(Path(__file__).parent / "tools" / "document-processor" / "src"))


@readable(
    intent="Test that openpyxl warnings are suppressed.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the openpyxl warnings behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_openpyxl_warnings():
    """Test that openpyxl warnings are suppressed."""
    print("Testing openpyxl warnings suppression...")
    try:
        from openpyxl_warnings import suppress_openpyxl_warnings
        suppress_openpyxl_warnings()
        print("✓ openpyxl warnings suppression works")
        return True
    except Exception as e:
        print(f"✗ openpyxl warnings suppression failed: {e}")
        return False


@readable(
    intent="Test document validation.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the document validator behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_document_validator():
    """Test document validation."""
    print("\nTesting document validator...")
    try:
        from document_validator import validate_document_file, is_scanned_pdf
        
        # Test with a non-existent file
        test_file = Path("/tmp/nonexistent.txt")
        is_valid, message = validate_document_file(test_file)
        if not is_valid and "not found" in message:
            print("✓ Document validator correctly detects missing files")
        else:
            print(f"✗ Document validator failed: {is_valid}, {message}")
            return False
        
        # Test with current directory
        current_dir = Path(__file__).parent
        is_valid, message = validate_document_file(current_dir)
        if not is_valid and "not a file" in message:
            print("✓ Document validator correctly detects directories")
        else:
            print(f"✗ Document validator failed: {is_valid}, {message}")
            return False
        
        return True
    except Exception as e:
        print(f"✗ Document validator test failed: {e}")
        return False


@readable(
    intent="Test temporary file management.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the temp file manager behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_temp_file_manager():
    """Test temporary file management."""
    print("\nTesting temp file manager...")
    try:
        from temp_file_manager import TempFileManager
        
        manager = TempFileManager("/tmp/test-rag-work")
        
        # Create temp directory
        temp_dir = manager.create_temp_dir()
        if temp_dir.exists():
            print("✓ Temp directory creation works")
        else:
            print("✗ Temp directory creation failed")
            return False
        
        # Create temp file
        temp_file = manager.create_temp_file(suffix=".txt")
        if temp_file.exists():
            print("✓ Temp file creation works")
        else:
            print("✗ Temp file creation failed")
            return False
        
        # Cleanup
        manager.cleanup(keep_base=False)
        if not temp_dir.exists() and not temp_file.exists():
            print("✓ Temp cleanup works")
        else:
            print("✗ Temp cleanup failed")
            return False
        
        return True
    except Exception as e:
        print(f"✗ Temp file manager test failed: {e}")
        return False


@readable(
    intent="Test memory configuration.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the memory config behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_memory_config():
    """Test memory configuration."""
    print("\nTesting memory configuration...")
    try:
        from memory_config import get_system_memory_info, get_recommended_memory_limits
        
        # Get system memory info
        mem_info = get_system_memory_info()
        if 'total_memory_gb' in mem_info:
            print(f"✓ System memory info: {mem_info['total_memory_gb']:.1f}GB total")
        else:
            print("✗ Could not get system memory info")
            return False
        
        # Get recommended limits
        limits = get_recommended_memory_limits()
        if 'libreoffice_memory' in limits:
            print(f"✓ Recommended limits: LibreOffice={limits['libreoffice_memory']}")
        else:
            print("✗ Could not get recommended limits")
            return False
        
        return True
    except Exception as e:
        print(f"✗ Memory configuration test failed: {e}")
        return False


@readable(
    intent="Test application initialization.",
    steps=[
        "Set up the inputs and collaborators for the scenario.",
        "Run the init app behavior under test.",
        "Check the observable result and assertions.",
    ],
    criteria=[
        "The assertions confirm the documented behavior.",
    ],
)
def test_init_app():
    """Test application initialization."""
    print("\nTesting application initialization...")
    try:
        from init_app import initialize_application, get_config
        
        # Initialize application
        success = initialize_application()
        if success:
            print("✓ Application initialization works")
        else:
            print("✗ Application initialization failed")
            return False
        
        # Get configuration
        config = get_config()
        config_dict = config.to_dict()
        if 'max_file_size_mb' in config_dict:
            print(f"✓ Configuration loaded: max_file_size={config_dict['max_file_size_mb']}MB")
        else:
            print("✗ Configuration not loaded properly")
            return False
        
        return True
    except Exception as e:
        print(f"✗ Application initialization test failed: {e}")
        return False


def main():
    """Run all tests."""
    print("=" * 60)
    print("Testing RAG Document Processor Improvements")
    print("=" * 60)
    
    tests = [
        test_openpyxl_warnings,
        test_document_validator,
        test_temp_file_manager,
        test_memory_config,
        test_init_app,
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"✗ Test {test.__name__} crashed: {e}")
            results.append(False)
    
    print("\n" + "=" * 60)
    print("Test Summary:")
    print("=" * 60)
    
    passed = sum(results)
    total = len(results)
    
    for i, (test, result) in enumerate(zip(tests, results), 1):
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{i:2d}. {test.__name__:30} {status}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✓ All improvements are working correctly!")
        return 0
    else:
        print(f"\n✗ {total - passed} tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
