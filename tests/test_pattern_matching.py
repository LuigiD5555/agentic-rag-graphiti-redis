#!/usr/bin/env python3
"""Test pattern matching for directory exclusion."""

import sys
sys.path.insert(0, '.')

from src.workflows.ingestion.discovery.pattern_matching import PatternMatcher

def test_pattern_matching():
    """Test that pattern matching works for backup directories."""
    matcher = PatternMatcher()
    
    # Test cases from .ingestignore
    test_cases = [
        # (path_to_test, patterns_set, expected_result)
        ("/mnt/Documents/Documents/Cline/MCP/claude-code-plugins-plus-skills/backups/", 
         {"/mnt/Documents/Documents/Cline/MCP/claude-code-plugins-plus-skills/backups/"}, 
         True),
        
        ("/mnt/Documents/Documents/Cline/MCP/claude-code-plugins-plus-skills/backups/plugin-backups/", 
         {"/mnt/Documents/Documents/Cline/MCP/claude-code-plugins-plus-skills/backups/"}, 
         True),
        
        ("/mnt/Documents/Documents/Cline/MCP/claude-code-plugins-plus-skills/backups/plugin-backups/deployment-rollback-manager_20251020_070125", 
         {"/mnt/Documents/Documents/Cline/MCP/claude-code-plugins-plus-skills/backups/"}, 
         True),
        
        ("/mnt/Documents/Documents/Cline/MCP/claude-code-plugins-plus-skills/backups/plugin-backups/deployment-rollback-manager_20251020_070125/file.txt", 
         {"/mnt/Documents/Documents/Cline/MCP/claude-code-plugins-plus-skills/backups/"}, 
         True),
        
        ("/mnt/Documents/Documents/Cline/other-directory/file.txt", 
         {"/mnt/Documents/Documents/Cline/"}, 
         True),
    ]
    
    print("Testing pattern matching for directory exclusion...")
    print("=" * 60)
    
    all_passed = True
    for path, patterns, expected in test_cases:
        result = matcher.matches_any_glob(path, patterns, absolute_path=path)
        status = "✓" if result == expected else "✗"
        print(f"{status} Path: {path}")
        print(f"  Patterns: {patterns}")
        print(f"  Expected: {expected}, Got: {result}")
        if result != expected:
            all_passed = False
        print()
    
    print("=" * 60)
    if all_passed:
        print("All pattern matching tests passed!")
    else:
        print("Some pattern matching tests failed!")
        sys.exit(1)

if __name__ == "__main__":
    test_pattern_matching()