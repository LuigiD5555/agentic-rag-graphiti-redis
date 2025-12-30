#!/usr/bin/env python3
"""
Example: Managing External Volumes via API

This demonstrates how to use the volumes API endpoints to manage external volumes
from Open WebUI or any other client.

Usage:
    python examples/manage_volumes_api.py
"""

import requests
import json

# Base URL for the RAG API
BASE_URL = "http://localhost:8000"


def list_volumes():
    """List all configured external volumes."""
    print("\n=== Listing External Volumes ===")
    response = requests.get(f"{BASE_URL}/volumes/")
    response.raise_for_status()

    data = response.json()
    volumes = data.get("volumes", [])

    if not volumes:
        print("No external volumes configured.")
    else:
        for vol in volumes:
            print(f"\n  {vol['name']}:")
            print(f"    Primary:  {vol['primary']}")
            print(f"    Fallback: {vol['fallback']}")
            print(f"    Mount:    {vol['mount']}")

    return volumes


def get_volumes_status():
    """Get status of all volumes (available/unavailable)."""
    print("\n=== Volumes Status ===")
    response = requests.get(f"{BASE_URL}/volumes/status")
    response.raise_for_status()

    statuses = response.json()

    for status in statuses:
        available_icon = "✓" if status['is_available'] else "✗"
        marker_icon = "✓" if status['marker_exists'] else "✗"

        print(f"\n  {status['name']}:")
        print(f"    Available: {available_icon} {status['is_available']}")
        print(f"    Marker:    {marker_icon} {status['marker_exists']}")
        print(f"    Primary:   {status['primary']}")


def add_volume(name: str, primary: str, fallback: str, mount: str):
    """Add a new external volume."""
    print(f"\n=== Adding Volume: {name} ===")

    payload = {
        "name": name,
        "primary": primary,
        "fallback": fallback,
        "mount": mount
    }

    response = requests.post(f"{BASE_URL}/volumes/add", json=payload)

    if response.status_code == 201:
        print(f"✓ Successfully added volume '{name}'")
        return response.json()
    elif response.status_code == 400:
        print(f"✗ Volume '{name}' already exists")
        return None
    else:
        response.raise_for_status()


def update_volume(name: str, primary: str, fallback: str, mount: str):
    """Update an existing volume."""
    print(f"\n=== Updating Volume: {name} ===")

    payload = {
        "name": name,
        "primary": primary,
        "fallback": fallback,
        "mount": mount
    }

    response = requests.put(f"{BASE_URL}/volumes/{name}", json=payload)

    if response.status_code == 200:
        print(f"✓ Successfully updated volume '{name}'")
        return response.json()
    elif response.status_code == 404:
        print(f"✗ Volume '{name}' not found")
        return None
    else:
        response.raise_for_status()


def remove_volume(name: str):
    """Remove a volume."""
    print(f"\n=== Removing Volume: {name} ===")

    response = requests.delete(f"{BASE_URL}/volumes/{name}")

    if response.status_code == 200:
        print(f"✓ Successfully removed volume '{name}'")
        return response.json()
    elif response.status_code == 404:
        print(f"✗ Volume '{name}' not found")
        return None
    else:
        response.raise_for_status()


def mark_volume_available(name: str):
    """Mark a volume as available by creating .volume-available marker."""
    print(f"\n=== Marking Volume as Available: {name} ===")

    response = requests.post(f"{BASE_URL}/volumes/{name}/mark-available")

    if response.status_code == 200:
        data = response.json()
        print(f"✓ Marked volume '{name}' as available")
        print(f"  Marker: {data['marker_path']}")
        return data
    elif response.status_code == 404:
        print(f"✗ Volume '{name}' not found")
        return None
    elif response.status_code == 400:
        print(f"✗ Primary path does not exist")
        return None
    else:
        response.raise_for_status()


def main():
    """Main example workflow."""
    print("=" * 60)
    print("External Volumes Management API Demo")
    print("=" * 60)

    # List current volumes
    volumes = list_volumes()

    # Get volumes status
    get_volumes_status()

    # Example: Add a new volume (uncomment to test)
    # add_volume(
    #     name="Research",
    #     primary="/media/usb/research",
    #     fallback="./data/research-fallback",
    #     mount="/mnt/resources/Research"
    # )

    # Example: Update an existing volume (uncomment to test)
    # update_volume(
    #     name="Libros",
    #     primary="/mnt/resources/Libros",
    #     fallback="./data/libros-fallback",
    #     mount="/mnt/resources/Libros"
    # )

    # Example: Mark a volume as available (uncomment to test)
    # mark_volume_available("Libros")

    # Example: Remove a volume (uncomment to test)
    # remove_volume("Research")

    print("\n" + "=" * 60)
    print("Demo completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except requests.exceptions.ConnectionError:
        print("\n✗ ERROR: Could not connect to API at", BASE_URL)
        print("  Make sure the RAG API is running (./start-everything.sh)")
    except Exception as e:
        print(f"\n✗ ERROR: {e}")
        raise
