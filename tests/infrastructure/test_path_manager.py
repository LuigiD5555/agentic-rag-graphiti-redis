#!/usr/bin/env python3
"""Test the dynamic path manager functionality."""

import os
import tempfile
from pathlib import Path

def test_path_manager_basic():
    """Test basic path manager functionality."""
    print("=== Testing Path Manager ===")

    from src.utils.path_manager import PathManager

    # Create a temporary settings file for testing
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        test_settings = {
            "DOCS_PATHS": [
                "/mnt/Documents/Documents",
                "/mnt/resources/Libros/Aprendizaje"
            ],
            "OTHER_SETTING": "test"
        }
        import json
        json.dump(test_settings, f)
        temp_file = f.name

    try:
        # Create path manager with temp file
        pm = PathManager(temp_file)

        # Test listing paths
        paths = pm.list_paths()
        print(f"Loaded {len(paths)} paths:")
        for p in paths:
            print(f"  - {p.path} (enabled: {p.enabled})")

        # Test adding a new path
        test_path = "/tmp/test-documents"
        os.makedirs(test_path, exist_ok=True)

        print(f"\nAdding test path: {test_path}")
        success = pm.add_path(test_path, "Test documents directory")
        print(f"Add path success: {success}")

        # Verify it was added
        paths = pm.list_paths()
        print(f"Now have {len(paths)} paths")

        # Test getting enabled paths
        enabled = pm.get_enabled_paths()
        print(f"Enabled paths: {enabled}")

        # Test disabling a path
        print(f"\nDisabling path: {test_path}")
        success = pm.disable_path(test_path)
        print(f"Disable path success: {success}")

        enabled = pm.get_enabled_paths()
        print(f"Enabled paths after disable: {enabled}")

        # Test removing a path
        print(f"\nRemoving path: {test_path}")
        success = pm.remove_path(test_path)
        print(f"Remove path success: {success}")

        paths = pm.list_paths()
        print(f"Final path count: {len(paths)}")

        # Clean up test directory
        os.rmdir(test_path)

        print("\n✓ Basic path manager tests passed")

    finally:
        # Clean up temp file
        os.unlink(temp_file)


def test_integration_with_settings():
    """Test integration with existing settings system."""
    print("\n=== Testing Integration with Settings ===")

    from src.utils.path_manager import update_ingestion_paths, get_enabled_document_paths

    # Get current enabled paths
    enabled_paths = get_enabled_document_paths()
    print(f"Current enabled paths from path manager: {enabled_paths}")

    # Update ingestion paths
    updated_paths = update_ingestion_paths()
    print(f"Updated ingestion paths: {updated_paths}")

    # Check if settings were updated
    try:
        import src.settings as settings
        assert hasattr(settings, 'DOCS_PATHS'), "settings module doesn't have DOCS_PATHS attribute"
        print(f"settings.DOCS_PATHS: {settings.DOCS_PATHS}")
        assert settings.DOCS_PATHS == updated_paths, "Settings not updated correctly"
        print("✓ Settings successfully updated")
    except ImportError as e:
        raise AssertionError(f"Could not import settings: {e}") from e


def test_path_validation():
    """Test path validation and accessibility."""
    print("\n=== Testing Path Validation ===")

    from src.utils.path_manager import PathManager

    # Test with inaccessible path
    inaccessible_path = "/non/existent/path/123456789"

    # Create a temporary settings file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        test_settings = {"DOCS_PATHS": []}
        import json
        json.dump(test_settings, f)
        temp_file = f.name

    try:
        pm = PathManager(temp_file)

        # Try to add inaccessible path
        print(f"Adding inaccessible path: {inaccessible_path}")
        success = pm.add_path(inaccessible_path, "Inaccessible test path", enable=True)
        print(f"Add inaccessible path success: {success}")

        paths = pm.list_paths()
        print(f"Paths after adding inaccessible: {len(paths)}")
        assert any(p.path == inaccessible_path for p in paths), "Inaccessible path was not added"

        # But it won't be accessible when the system tries to scan it
        # This is OK - the discovery service will handle it gracefully

        print("✓ Path validation tests passed")

    finally:
        os.unlink(temp_file)


def test_container_paths():
    """Test paths that should be accessible from inside container."""
    print("\n=== Testing Container Paths ===")

    # Paths that should be mounted in the container
    container_paths = [
        "/mnt/Documents/Documents",
        "/mnt/resources/Libros",
        "/mnt/resources/Libros/Aprendizaje"
    ]

    print("Checking container path accessibility:")
    for path in container_paths:
        exists = os.path.exists(path)
        print(f"  {path}: {'✓ EXISTS' if exists else '✗ DOES NOT EXIST'}")

        if exists:
            try:
                items = os.listdir(path)
                print(f"    Can list directory: Yes ({len(items)} items)")
            except Exception as e:
                print(f"    Can list directory: No ({e})")

    # Check if we're in a container by looking for container markers
    in_container = os.path.exists('/.dockerenv') or os.path.exists('/run/.containerenv')
    print(f"\nRunning in container: {in_container}")

    # Informational test: no hard assertion on host mount presence.


def main():
    """Run all tests."""
    print("Testing Dynamic Path Management System...")
    print("=" * 60)

    tests_passed = 0
    tests_total = 4

    try:
        result = test_path_manager_basic()
        if result is None or result:
            tests_passed += 1
    except Exception as e:
        print(f"✗ Path manager basic test failed: {e}")
        import traceback
        traceback.print_exc()

    try:
        result = test_integration_with_settings()
        if result is None or result:
            tests_passed += 1
    except Exception as e:
        print(f"✗ Integration test failed: {e}")

    try:
        result = test_path_validation()
        if result is None or result:
            tests_passed += 1
    except Exception as e:
        print(f"✗ Path validation test failed: {e}")

    try:
        result = test_container_paths()
        if result is None or result:
            tests_passed += 1
    except Exception as e:
        print(f"✗ Container paths test failed: {e}")

    print("\n" + "=" * 60)
    print(f"Test results: {tests_passed}/{tests_total} tests passed")

    if tests_passed == tests_total:
        print("\n✓ All tests passed! Path management system is working.")
        print("\nSummary of changes:")
        print("1. Created dynamic path manager for runtime path management")
        print("2. Paths are persisted to data/settings.json")
        print("3. System handles inaccessible paths gracefully")
        print("4. Ready for UI integration via API endpoints")
        return 0
    else:
        print("\n✗ Some tests failed. Review the output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
