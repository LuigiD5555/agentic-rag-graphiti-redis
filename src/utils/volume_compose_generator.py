#!/usr/bin/env python3
"""
Volume Compose Generator - Generates volume mount entries for podman-compose.yml

This script reads EXTERNAL_VOLUMES from .env and generates the appropriate
volume mount configurations for the app container.
"""

import os
import json
import sys
from pathlib import Path
from typing import List, Dict


def load_env_file(env_path: str = ".env") -> Dict[str, str]:
    """Load environment variables from .env file."""
    env_vars = {}

    if not os.path.exists(env_path):
        return env_vars

    with open(env_path, 'r') as f:
        for line in f:
            line = line.strip()
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                continue

            # Parse KEY=VALUE, handling quotes
            if '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                value = value.strip()

                # Remove quotes if present
                if value.startswith('"') and value.endswith('"'):
                    value = value[1:-1]
                elif value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]

                env_vars[key] = value

    return env_vars


def load_external_volumes_config(env_vars: Dict[str, str] = None) -> List[Dict[str, str]]:
    """
    Load external volumes configuration from environment.

    Returns:
        List of volume configurations
    """
    if env_vars is None:
        env_vars = load_env_file()

    config_str = env_vars.get("EXTERNAL_VOLUMES", "")

    if not config_str:
        libros_primary = env_vars.get("HOST_LIBROS_DIR", "/mnt/resources/Libros")
        libros_fallback = env_vars.get("FALLBACK_LIBROS_DIR", "./data/libros-fallback")
        return [{
            "name": "Libros",
            "primary": libros_primary,
            "fallback": libros_fallback,
            "mount": "/mnt/resources/Libros"
        }]

    try:
        volumes = json.loads(config_str)
        if not isinstance(volumes, list):
            print(f"ERROR: EXTERNAL_VOLUMES must be a JSON array, got: {type(volumes)}", file=sys.stderr)
            return []
        return volumes
    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to parse EXTERNAL_VOLUMES JSON: {e}", file=sys.stderr)
        return []


def generate_volume_mounts(indent: int = 6) -> str:
    """
    Generate volume mount entries for podman-compose.yml

    Args:
        indent: Number of spaces to indent (default 6 for inside 'volumes:' in compose)

    Returns:
        String with volume mount entries
    """
    volumes_config = load_external_volumes_config()

    if not volumes_config:
        return ""

    lines = []
    prefix = " " * indent

    for vol_config in volumes_config:
        name = vol_config.get("name")
        primary = vol_config.get("primary")
        fallback = vol_config.get("fallback")
        mount_point = vol_config.get("mount")

        if not all([name, primary, fallback, mount_point]):
            print(f"WARNING: Skipping incomplete volume config: {vol_config}", file=sys.stderr)
            continue

        # Generate the volume mount line
        # Format: - ${HOST_X_DIR:-/fallback/path}:/mount/point:Z
        line = f"{prefix}- ${{HOST_{name.upper()}_DIR:-{fallback}}}:{mount_point}:Z"
        lines.append(line)

        # Add comment above the line
        comment = f"{prefix}# External volume: {name} (auto-detected from EXTERNAL_VOLUMES)"
        lines.insert(-1, comment)

    return "\n".join(lines)


def print_volume_list():
    """Print configured volumes for verification."""
    volumes_config = load_external_volumes_config()

    if not volumes_config:
        print("No external volumes configured.")
        return

    print(f"Configured external volumes ({len(volumes_config)}):")
    print("-" * 60)

    for vol_config in volumes_config:
        name = vol_config.get("name", "???")
        primary = vol_config.get("primary", "???")
        fallback = vol_config.get("fallback", "???")
        mount_point = vol_config.get("mount", "???")

        print(f"  {name}:")
        print(f"    Primary:  {primary}")
        print(f"    Fallback: {fallback}")
        print(f"    Mount:    {mount_point}")

        # Check if marker exists
        marker_path = os.path.join(primary, ".volume-available")
        if os.path.exists(marker_path):
            print(f"    Status:   ✓ Available (marker found)")
        else:
            print(f"    Status:   ⚠ Not available (using fallback)")
        print()


def main():
    """Main entry point."""
    if len(sys.argv) > 1:
        cmd = sys.argv[1]

        if cmd == "list":
            print_volume_list()
        elif cmd == "generate":
            print(generate_volume_mounts())
        elif cmd == "help":
            print("Usage:")
            print("  python -m src.utils.volume_compose_generator list      - List configured volumes")
            print("  python -m src.utils.volume_compose_generator generate  - Generate compose mount entries")
        else:
            print(f"Unknown command: {cmd}", file=sys.stderr)
            sys.exit(1)
    else:
        # Default: list volumes
        print_volume_list()


if __name__ == "__main__":
    main()
