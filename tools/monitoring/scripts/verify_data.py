#!/usr/bin/env python3
"""Verify Weaviate database has data and can be queried."""
import weaviate
from src.rag.engine import AppConfig

def main():
    config = AppConfig()

    print("=" * 70)
    print("WEAVIATE DATA VERIFICATION")
    print("=" * 70)
    print(f"\nConnecting to: {config.WEAVIATE_URL}")
    print(f"Collection: {config.WEAVIATE_CLASS}")
    print(f"Tenant: {config.WEAVIATE_DEFAULT_TENANT}")
    print(f"GRPC Port: {config.WEAVIATE_GRPC_PORT}")

    # Connect to Weaviate
    try:
        client = weaviate.connect_to_local(
            host=config.WEAVIATE_URL.replace("http://", "").replace("https://", "").split(":")[0],
            port=int(config.WEAVIATE_URL.split(":")[-1]) if ":" in config.WEAVIATE_URL else 8080,
            grpc_port=config.WEAVIATE_GRPC_PORT,
        )
        print("\n✓ Connected to Weaviate")
    except Exception as e:
        print(f"\n✗ Failed to connect: {e}")
        return 1

    try:
        # List all collections
        print("\n" + "-" * 70)
        print("Available Collections:")
        print("-" * 70)
        collections = client.collections.list_all()
        if not collections:
            print("  No collections found!")
        else:
            for name, config_obj in collections.items():
                print(f"  - {name}")

        # Check if our collection exists
        collection_name = config.WEAVIATE_CLASS
        if collection_name not in collections:
            print(f"\n✗ Collection '{collection_name}' does not exist!")
            print("\nAvailable collections:", list(collections.keys()))
            return 1

        print(f"\n✓ Collection '{collection_name}' exists")

        # Get collection with tenant
        if config.WEAVIATE_DEFAULT_TENANT:
            collection = client.collections.get(collection_name).with_tenant(config.WEAVIATE_DEFAULT_TENANT)
            print(f"✓ Using tenant: {config.WEAVIATE_DEFAULT_TENANT}")
        else:
            collection = client.collections.get(collection_name)
            print("✓ No tenant specified (using default)")

        # Get total count
        print("\n" + "-" * 70)
        print("Collection Statistics:")
        print("-" * 70)
        try:
            result = collection.aggregate.over_all(total_count=True)
            total_count = result.total_count if result else 0
            print(f"Total documents: {total_count:,}")

            if total_count == 0:
                print("\n⚠ WARNING: Collection is empty! No documents to query.")
                print("\nYou need to run ingestion first:")
                print("  python -m src.ingestion.cli --streaming")
                return 1
            else:
                print(f"\n✓ Collection has {total_count:,} documents")
        except Exception as e:
            print(f"✗ Failed to get count: {e}")
            return 1

        # Sample a few documents
        print("\n" + "-" * 70)
        print("Sample Documents (first 3):")
        print("-" * 70)
        try:
            response = collection.query.fetch_objects(limit=3)
            objects = response.objects if response else []

            if not objects:
                print("  No objects found (collection might be empty)")
            else:
                for i, obj in enumerate(objects, 1):
                    props = obj.properties
                    text = props.get("text", "")[:100] + "..." if len(props.get("text", "")) > 100 else props.get("text", "")
                    print(f"\n  Document {i}:")
                    print(f"    UUID: {obj.uuid}")
                    print(f"    Source: {props.get('source', 'N/A')}")
                    print(f"    Chunk Index: {props.get('chunk_index', 'N/A')}")
                    print(f"    Text: {text}")
        except Exception as e:
            print(f"✗ Failed to fetch sample documents: {e}")

        # Test a simple query
        print("\n" + "-" * 70)
        print("Test Query (searching for 'python'):")
        print("-" * 70)
        try:
            from weaviate.classes.query import MetadataQuery

            response = collection.query.hybrid(
                query="python",
                limit=3,
                alpha=0.7,
                return_metadata=MetadataQuery(score=True),
            )

            results = response.objects if response else []
            print(f"Found {len(results)} results")

            for i, obj in enumerate(results, 1):
                props = obj.properties
                text = props.get("text", "")[:100] + "..." if len(props.get("text", "")) > 100 else props.get("text", "")
                score = obj.metadata.score if obj.metadata else 0.0
                print(f"\n  Result {i} (score: {score:.4f}):")
                print(f"    Source: {props.get('source', 'N/A')}")
                print(f"    Text: {text}")
        except Exception as e:
            print(f"✗ Query failed: {e}")
            import traceback
            traceback.print_exc()

        print("\n" + "=" * 70)
        print("VERIFICATION COMPLETE")
        print("=" * 70)

    finally:
        client.close()
        print("\n✓ Connection closed")

    return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())