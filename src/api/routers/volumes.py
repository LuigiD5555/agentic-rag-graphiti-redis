"""
API endpoints for managing external volumes configuration.

These endpoints allow Open WebUI to view and manage external volumes
(USB drives, network shares, etc.) for RAG document ingestion.
"""

import os
import json
from typing import List, Dict, Any
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

# FIX: Import settings directly from src.settings, not non-existent src.config
import src.settings as app_settings


router = APIRouter(prefix="/volumes", tags=["volumes"])


# ============================================================================
# Helper Functions
# ============================================================================

def update_settings_json(updates: Dict[str, Any]) -> None:
    """
    Update settings.json file with new values.

    Creates the file if it doesn't exist.
    Merges updates with existing settings.
    """
    settings_file = app_settings.USER_SETTINGS_FILE

    # Load existing settings
    existing_settings = {}
    if settings_file.exists():
        try:
            with open(settings_file, 'r') as f:
                existing_settings = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass  # Start fresh if file is corrupted

    # Merge updates
    existing_settings.update(updates)

    # Ensure directory exists
    settings_file.parent.mkdir(parents=True, exist_ok=True)

    # Write back
    with open(settings_file, 'w') as f:
        json.dump(existing_settings, f, indent=2)


# ============================================================================
# Pydantic Models
# ============================================================================

class ExternalVolume(BaseModel):
    """Model for an external volume configuration."""

    name: str = Field(..., description="Human-readable identifier for the volume")
    primary: str = Field(..., description="Primary path on host where volume is mounted")
    fallback: str = Field(..., description="Fallback directory when volume unavailable")
    mount: str = Field(..., description="Path inside container where volume is accessible")


class ExternalVolumesConfig(BaseModel):
    """Configuration for all external volumes."""

    volumes: List[ExternalVolume] = Field(default_factory=list)


class VolumeStatus(BaseModel):
    """Status information for a volume."""

    name: str
    primary: str
    fallback: str
    mount: str
    is_available: bool
    marker_exists: bool


# ============================================================================
# API Endpoints
# ============================================================================

@router.get("/", response_model=ExternalVolumesConfig)
async def get_external_volumes() -> ExternalVolumesConfig:
    """
    Get all configured external volumes.

    Returns volumes from settings.json if available, otherwise from .env
    """
    from src.utils.volume_monitor import load_external_volumes_config

    volumes = load_external_volumes_config()
    return ExternalVolumesConfig(
        volumes=[ExternalVolume(**vol) for vol in volumes]
    )


@router.post("/", status_code=status.HTTP_201_CREATED)
async def update_external_volumes(config: ExternalVolumesConfig) -> Dict[str, Any]:
    """
    Update external volumes configuration in settings.json.

    This persists the configuration across container restarts.
    """
    # Convert to list of dicts
    volumes_data = [vol.model_dump() for vol in config.volumes]

    # Update settings.json
    update_settings_json({"EXTERNAL_VOLUMES": volumes_data})

    # Update environment variables for immediate effect
    for vol in config.volumes:
        env_var_name = f"HOST_{vol.name.upper()}_DIR"
        os.environ[env_var_name] = vol.primary

    return {
        "success": True,
        "message": f"Updated {len(volumes_data)} external volume(s)",
        "volumes": volumes_data
    }


@router.post("/add", status_code=status.HTTP_201_CREATED)
async def add_external_volume(volume: ExternalVolume) -> Dict[str, Any]:
    """
    Add a new external volume to the configuration.
    """
    # Load current configuration
    current_config = await get_external_volumes()

    # Check if volume with same name already exists
    for existing_vol in current_config.volumes:
        if existing_vol.name == volume.name:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Volume with name '{volume.name}' already exists"
            )

    # Add new volume
    current_config.volumes.append(volume)

    # Save updated configuration
    result = await update_external_volumes(current_config)
    return result


@router.delete("/{volume_name}")
async def remove_external_volume(volume_name: str) -> Dict[str, Any]:
    """
    Remove an external volume from the configuration.
    """
    # Load current configuration
    current_config = await get_external_volumes()

    # Find and remove volume
    volumes_before = len(current_config.volumes)
    current_config.volumes = [
        vol for vol in current_config.volumes
        if vol.name != volume_name
    ]

    if len(current_config.volumes) == volumes_before:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Volume '{volume_name}' not found"
        )

    # Save updated configuration
    result = await update_external_volumes(current_config)
    result["message"] = f"Removed volume '{volume_name}'"
    return result


@router.put("/{volume_name}")
async def update_volume(volume_name: str, volume: ExternalVolume) -> Dict[str, Any]:
    """
    Update an existing external volume configuration.
    """
    # Load current configuration
    current_config = await get_external_volumes()

    # Find and update volume
    found = False
    for i, existing_vol in enumerate(current_config.volumes):
        if existing_vol.name == volume_name:
            current_config.volumes[i] = volume
            found = True
            break

    if not found:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Volume '{volume_name}' not found"
        )

    # Save updated configuration
    result = await update_external_volumes(current_config)
    result["message"] = f"Updated volume '{volume_name}'"
    return result


@router.get("/status", response_model=List[VolumeStatus])
async def get_volumes_status() -> List[VolumeStatus]:
    """
    Get status of all configured volumes (available/unavailable).

    Checks for .volume-available markers to determine if volumes are mounted.
    """
    from src.utils.volume_monitor import load_external_volumes_config

    volumes = load_external_volumes_config()
    status_list = []

    for vol in volumes:
        primary_path = vol.get("primary", "")
        marker_path = os.path.join(primary_path, ".volume-available")

        is_available = os.path.exists(primary_path)
        marker_exists = os.path.exists(marker_path)

        status_list.append(VolumeStatus(
            name=vol.get("name", ""),
            primary=primary_path,
            fallback=vol.get("fallback", ""),
            mount=vol.get("mount", ""),
            is_available=is_available,
            marker_exists=marker_exists
        ))

    return status_list


@router.post("/{volume_name}/mark-available")
async def mark_volume_available(volume_name: str) -> Dict[str, Any]:
    """
    Create .volume-available marker for a volume.

    This marks the volume as "available" for the detection system.
    """
    from src.utils.volume_monitor import load_external_volumes_config

    volumes = load_external_volumes_config()

    # Find the volume
    target_volume = None
    for vol in volumes:
        if vol.get("name") == volume_name:
            target_volume = vol
            break

    if not target_volume:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Volume '{volume_name}' not found"
        )

    primary_path = target_volume.get("primary", "")
    if not os.path.exists(primary_path):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Primary path '{primary_path}' does not exist"
        )

    # Create marker file
    marker_path = os.path.join(primary_path, ".volume-available")
    try:
        Path(marker_path).touch()
        return {
            "success": True,
            "message": f"Marked volume '{volume_name}' as available",
            "marker_path": marker_path
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create marker: {str(e)}"
        )
