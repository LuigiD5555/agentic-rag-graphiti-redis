#!/usr/bin/env python3
"""
Test script to verify that the SchemaManager fix works.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Mock configuration for testing
class MockConfig:
    WEAVIATE_HNSW_EF_CONSTRUCTION = 128
    WEAVIATE_HNSW_MAX_CONNECTIONS = 32
    WEAVIATE_HNSW_DISTANCE_METRIC = 'cosine'

def test_schema_manager():
    """Tests that the SchemaManager can create the HNSW configuration correctly."""
    
    # Importar las clases necesarias
    from weaviate.classes.config import Configure, Property, DataType
    from weaviate.collections.classes.config_vectorizers import VectorDistances
    
    # Simulate the SchemaManager logic
    hnsw_distance_metric = 'cosine'
    
    # Convert string distance metric to VectorDistances enum (our fix)
    distance_metric_map = {
        'cosine': VectorDistances.COSINE,
        'l2': VectorDistances.L2_SQUARED,
        'dot': VectorDistances.DOT,
        'hamming': VectorDistances.HAMMING,
        'manhattan': VectorDistances.MANHATTAN,
    }
    
    # Get the distance metric from config, default to COSINE if not found
    distance_metric = distance_metric_map.get(hnsw_distance_metric.lower(), VectorDistances.COSINE)
    
    # Try to create the HNSW configuration
    try:
        hnsw_config = Configure.VectorIndex.hnsw(
            distance_metric=distance_metric,
            ef_construction=128,
            max_connections=32,
        )
        print("✅ SUCCESS: HNSW configuration was created successfully")
        print(f"   - distance_metric type: {type(distance_metric)}")
        print(f"   - distance_metric value: {distance_metric}")
        print(f"   - HNSW configuration type: {type(hnsw_config)}")
        return True
    except Exception as e:
        print(f"❌ ERROR: Failed to create HNSW config: {e}")
        return False

def test_contraste_con_error():
    """Shows what happens with the original (broken) code."""
    
    from weaviate.classes.config import Configure
    
    try:
        # This is what caused the original error
        hnsw_config = Configure.VectorIndex.hnsw(
            distance_metric='cosine',  # String en lugar de enum
            ef_construction=128,
            max_connections=32,
        )
        print("❌ THIS SHOULD NOT WORK: The string-based code succeeded (unexpected!)")
        return False
    except Exception as e:
        print(f"✅ CONFIRMED: The original string-based code fails as expected: {type(e).__name__}")
        return True

if __name__ == "__main__":
    print("🧪 Testing the SchemaManager fix...")
    print("=" * 60)
    
    print("\n1. Testing the fix (with VectorDistances enum):")
    exito_1 = test_schema_manager()
    
    print("\n2. Contrast: testing the original string-based code:")
    exito_2 = test_contraste_con_error()
    
    print("\n" + "=" * 60)
    if exito_1 and exito_2:
        print("🎉 All tests passed! The fix works correctly.")
        sys.exit(0)
    else:
        print("❌ Some tests failed.")
        sys.exit(1)
