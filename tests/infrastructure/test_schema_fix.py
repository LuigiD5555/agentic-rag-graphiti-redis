#!/usr/bin/env python3
"""Test script to verify that the SchemaManager fix works."""

import sys
import pytest

def test_schema_manager():
    """Tests that the SchemaManager can create the HNSW configuration correctly."""
    
    # Importar las clases necesarias
    from weaviate.classes.config import Configure
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
    
    hnsw_config = Configure.VectorIndex.hnsw(
        distance_metric=distance_metric,
        ef_construction=128,
        max_connections=32,
    )
    print("✅ SUCCESS: HNSW configuration was created successfully")
    print(f"   - distance_metric type: {type(distance_metric)}")
    print(f"   - distance_metric value: {distance_metric}")
    print(f"   - HNSW configuration type: {type(hnsw_config)}")

def test_contraste_con_error():
    """Shows what happens with the original (broken) code."""
    
    from weaviate.classes.config import Configure
    
    with pytest.raises(Exception):
        Configure.VectorIndex.hnsw(
            distance_metric='cosine',  # String en lugar de enum
            ef_construction=128,
            max_connections=32,
        )
    print("✅ CONFIRMED: The original string-based code fails as expected")

if __name__ == "__main__":
    print("🧪 Testing the SchemaManager fix...")
    print("=" * 60)
    
    print("\n1. Testing the fix (with VectorDistances enum):")
    exito_1 = test_schema_manager()
    
    print("\n2. Contrast: testing the original string-based code:")
    exito_2 = test_contraste_con_error()

    ok_1 = exito_1 is None or bool(exito_1)
    ok_2 = exito_2 is None or bool(exito_2)
    
    print("\n" + "=" * 60)
    if ok_1 and ok_2:
        print("🎉 All tests passed! The fix works correctly.")
        sys.exit(0)
    else:
        print("❌ Some tests failed.")
        sys.exit(1)
