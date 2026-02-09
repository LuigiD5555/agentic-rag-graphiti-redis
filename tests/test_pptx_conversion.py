#!/usr/bin/env python3
"""Test PPTX conversion with Redis-like resilience."""

import sys
import os
sys.path.insert(0, 'src')

from src.workflows.ingestion.loaders.office_client import OfficeToolClient

def test_pptx_conversion():
    """Test PPTX conversion with the new resilient client."""
    pptx_path = "/mnt/Documents/Documents/Presentation1.pptx"
    
    if not os.path.exists(pptx_path):
        print(f"Error: PPTX file not found at {pptx_path}")
        print("Please check if the file exists.")
        return False
    
    print(f"Testing PPTX conversion for: {pptx_path}")
    print(f"File exists: {os.path.exists(pptx_path)}")
    print(f"File size: {os.path.getsize(pptx_path)} bytes")
    
    # Create client with Redis-like resilience
    client = OfficeToolClient()
    
    print("\n1. Testing health check...")
    health = client.health_check()
    print(f"   Health check: {health}")
    
    if not health:
        print("   Service is not healthy. Testing wait_for_service...")
        available = client.wait_for_service(timeout_seconds=30)
        print(f"   Service available after wait: {available}")
        if not available:
            print("   ERROR: Service did not become available")
            return False
    
    print("\n2. Testing conversion...")
    try:
        # This will use the Redis-like retry logic
        text = client.convert_to_text(pptx_path)
        print(f"   SUCCESS: Conversion completed!")
        print(f"   Extracted text length: {len(text)} characters")
        print(f"   First 500 chars: {text[:500]}...")
        return True
    except Exception as e:
        print(f"   ERROR: Conversion failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("Testing OfficeToolClient with Redis-like resilience")
    print("=" * 60)
    
    success = test_pptx_conversion()
    
    print("\n" + "=" * 60)
    if success:
        print("✓ TEST PASSED: PPTX conversion works with Redis-like resilience")
    else:
        print("✗ TEST FAILED: PPTX conversion failed")
    print("=" * 60)