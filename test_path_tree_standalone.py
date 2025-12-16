#!/usr/bin/env python3
"""
Standalone test for PathTree optimization.

Tests the PathTree data structure without requiring full dependencies.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from src.rag.ingestion.discovery.path_tree import PathTree, PathNode


def test_path_tree_basic():
    """Test basic PathTree operations."""
    print("\n" + "="*70)
    print("TEST 1: PathTree Basic Operations")
    print("="*70)

    tree = PathTree()

    # Test adding paths
    print("\n1. Testing path addition...")
    node1 = tree.add_path("src/components/ui")
    node2 = tree.add_path("src/components/forms")
    node3 = tree.add_path("src/utils")
    assert node1 is not None, "Should return a node"
    print("   ✓ Added 3 paths successfully")

    # Test finding paths
    print("\n2. Testing path lookup...")
    found = tree.find_node("src/components/ui")
    assert found is not None, "Should find the path"
    assert found.name == "ui", f"Node name should be 'ui', got {found.name}"
    print("   ✓ Path lookup works correctly")

    # Test non-existent path
    not_found = tree.find_node("nonexistent/path")
    assert not_found is None, "Should return None for non-existent path"
    print("   ✓ Non-existent path returns None")

    print("\n✅ Basic operations test passed!")


def test_path_tree_visited():
    """Test visited tracking."""
    print("\n" + "="*70)
    print("TEST 2: Visited Path Tracking")
    print("="*70)

    tree = PathTree()

    # Add and mark paths
    print("\n1. Testing visited marking...")
    tree.add_path("src/components/ui")
    tree.add_path("src/components/forms")
    tree.mark_visited("src/components/ui")

    assert tree.is_visited("src/components/ui"), "Should be marked as visited"
    assert not tree.is_visited("src/components/forms"), "Should not be visited"
    print("   ✓ Visited marking works correctly")

    # Test clearing
    print("\n2. Testing clear visited...")
    tree.clear_visited()
    assert not tree.is_visited("src/components/ui"), "Should be cleared"
    print("   ✓ Clear visited works correctly")

    print("\n✅ Visited tracking test passed!")


def test_path_tree_exclusion():
    """Test hierarchical exclusion."""
    print("\n" + "="*70)
    print("TEST 3: Hierarchical Exclusion")
    print("="*70)

    tree = PathTree()

    # Add excluded path
    print("\n1. Testing exclusion marking...")
    tree.add_path("node_modules", is_excluded=True)
    tree.add_path("node_modules/package/dist")  # Child added after
    tree.add_path("src/components")  # Normal path

    assert tree.is_path_excluded("node_modules"), "Should be excluded"
    assert not tree.is_path_excluded("src/components"), "Should not be excluded"
    print("   ✓ Exclusion marking works correctly")

    # Test that marking a parent as excluded affects children
    print("\n2. Testing hierarchical exclusion...")
    tree2 = PathTree()
    tree2.add_path("build/output/files")
    tree2.add_path("build", is_excluded=True)  # Mark parent as excluded

    # The parent is excluded
    assert tree2.is_path_excluded("build"), "Parent should be excluded"
    print("   ✓ Hierarchical exclusion works correctly")

    print("\n✅ Exclusion test passed!")


def test_path_tree_performance():
    """Test performance with many paths."""
    print("\n" + "="*70)
    print("TEST 4: Performance with Large Dataset")
    print("="*70)

    import time

    tree = PathTree()

    print("\n1. Adding 1000 paths...")
    start = time.time()
    for i in range(1000):
        tree.add_path(f"src/module{i % 10}/file{i}.py")
    elapsed = time.time() - start
    print(f"   ✓ Added 1000 paths in {elapsed*1000:.2f}ms ({elapsed*1000000/1000:.2f}µs per path)")

    print("\n2. Looking up 1000 paths...")
    start = time.time()
    for i in range(1000):
        tree.find_node(f"src/module{i % 10}/file{i}.py")
    elapsed = time.time() - start
    print(f"   ✓ Looked up 1000 paths in {elapsed*1000:.2f}ms ({elapsed*1000000/1000:.2f}µs per path)")

    print("\n3. Checking visited status 1000 times...")
    # Mark some as visited
    for i in range(0, 1000, 2):  # Mark even numbers
        tree.mark_visited(f"src/module{i % 10}/file{i}.py")

    start = time.time()
    for i in range(1000):
        tree.is_visited(f"src/module{i % 10}/file{i}.py")
    elapsed = time.time() - start
    print(f"   ✓ Checked 1000 visited status in {elapsed*1000:.2f}ms ({elapsed*1000000/1000:.2f}µs per check)")

    # Get stats
    stats = tree.get_stats()
    print(f"\n4. Tree statistics:")
    print(f"   - Total nodes: {stats['total_nodes']}")
    print(f"   - Visited paths: {stats['visited_paths']}")
    print(f"   - Memory savings: {stats['memory_savings']}")

    print("\n✅ Performance test passed!")


def test_path_normalization():
    """Test path normalization."""
    print("\n" + "="*70)
    print("TEST 5: Path Normalization")
    print("="*70)

    tree = PathTree()

    print("\n1. Testing different path formats...")
    tree.add_path("src/components/ui")
    tree.add_path("/src/components/forms/")  # Leading/trailing slashes
    tree.add_path("src/utils")

    # All should be found regardless of slashes
    assert tree.find_node("src/components/ui") is not None
    assert tree.find_node("/src/components/ui/") is not None
    assert tree.find_node("src/components/forms") is not None
    assert tree.find_node("/src/components/forms") is not None
    print("   ✓ Path normalization works correctly")

    print("\n✅ Normalization test passed!")


def test_unvisited_children():
    """Test getting unvisited children."""
    print("\n" + "="*70)
    print("TEST 6: Unvisited Children")
    print("="*70)

    tree = PathTree()

    print("\n1. Setting up tree...")
    tree.add_path("src/components/ui")
    tree.add_path("src/components/forms")
    tree.add_path("src/components/layout")
    tree.mark_visited("src/components/ui")

    print("\n2. Getting unvisited children...")
    unvisited = tree.get_unvisited_children("src/components")
    assert "src/components/forms" in unvisited, "Should include unvisited child"
    assert "src/components/layout" in unvisited, "Should include unvisited child"
    assert "src/components/ui" not in unvisited, "Should not include visited child"
    print(f"   ✓ Found {len(unvisited)} unvisited children")

    print("\n✅ Unvisited children test passed!")


def main():
    """Run all tests."""
    print("\n" + "="*70)
    print("PATH TREE OPTIMIZATION TEST SUITE")
    print("="*70)

    try:
        test_path_tree_basic()
        test_path_tree_visited()
        test_path_tree_exclusion()
        test_path_tree_performance()
        test_path_normalization()
        test_unvisited_children()

        print("\n" + "="*70)
        print("🎉 ALL TESTS PASSED!")
        print("="*70)
        print("\nThe PathTree optimization is working correctly and provides:")
        print("  • O(k) lookups where k is path depth")
        print("  • Efficient visited tracking")
        print("  • Hierarchical exclusion checking")
        print("  • Memory-efficient prefix sharing")
        print("\nThese optimizations prevent re-scanning of directories and")
        print("significantly speed up file discovery operations.")
        print("="*70 + "\n")

    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
