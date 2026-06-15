#!/usr/bin/env python3
"""Debug pattern matching issues."""

import os
import sys

# Simple test without importing the whole project
def test_pattern_matching_simple():
    """Test pattern matching logic manually."""
    
    # Simulate the pattern matching logic from pattern_matching.py
    def simple_matches_any_glob(path, patterns, absolute_path=None):
        """Simplified version of pattern matching."""
        path = os.path.abspath(absolute_path or path).replace("\\", "/").rstrip("/") or "/"
        
        for pattern in patterns:
            pattern = pattern.rstrip("/")
            
            # Check if path starts with pattern (directory exclusion)
            if path.startswith(pattern):
                return True
            
            # Check exact match
            if path == pattern:
                return True
            
            # Check if pattern is a parent directory
            if pattern.endswith("/**") or pattern.endswith("/**/*"):
                base = pattern.rstrip("/**").rstrip("/**/*").rstrip("/")
                if path.startswith(base + "/"):
                    return True
        
        return False
    
    # Test cases
    test_cases = [
        # (path, pattern, expected)
        ("/mnt/Documents/Documents/Cline/MCP/claude-code-plugins-plus-skills/backups/",
         "/mnt/Documents/Documents/Cline/MCP/claude-code-plugins-plus-skills/backups",
         True),
        
        ("/mnt/Documents/Documents/Cline/MCP/claude-code-plugins-plus-skills/backups/plugin-backups/",
         "/mnt/Documents/Documents/Cline/MCP/claude-code-plugins-plus-skills/backups",
         True),
        
        ("/mnt/Documents/Documents/Cline/MCP/claude-code-plugins-plus-skills/backups/plugin-backups/deployment-rollback-manager_20251020_070125",
         "/mnt/Documents/Documents/Cline/MCP/claude-code-plugins-plus-skills/backups",
         True),
        
        ("/mnt/Documents/Documents/Cline/MCP/claude-code-plugins-plus-skills/backups/plugin-backups/deployment-rollback-manager_20251020_070125/file.txt",
         "/mnt/Documents/Documents/Cline/MCP/claude-code-plugins-plus-skills/backups",
         True),
    ]
    
    print("Testing pattern matching logic...")
    print("=" * 60)
    
    for path, pattern, expected in test_cases:
        result = simple_matches_any_glob(path, {pattern}, absolute_path=path)
        status = "✓" if result == expected else "✗"
        print(f"{status} Path: {path}")
        print(f"  Pattern: {pattern}")
        print(f"  Expected: {expected}, Got: {result}")
        print()
    
    print("=" * 60)
    
    # Also test the actual .ingestignore patterns
    print("\nTesting .ingestignore patterns...")
    print("=" * 60)
    
    with open(".ingestignore", "r") as f:
        lines = [line.strip() for line in f if line.strip() and not line.startswith("#")]
    
    print(f"Loaded {len(lines)} patterns from .ingestignore")
    print("First 10 patterns:")
    for i, pattern in enumerate(lines[:10]):
        print(f"  {i+1}. {pattern}")
    
    # Check if our backup pattern is there
    backup_pattern = "/mnt/Documents/Documents/Cline/MCP/claude-code-plugins-plus-skills/backups/"
    if backup_pattern in lines:
        print(f"\n✓ Backup pattern found: {backup_pattern}")
    else:
        print(f"\n✗ Backup pattern NOT found: {backup_pattern}")
        print("Looking for similar patterns...")
        for pattern in lines:
            if "backups" in pattern.lower():
                print(f"  Found: {pattern}")

if __name__ == "__main__":
    test_pattern_matching_simple()