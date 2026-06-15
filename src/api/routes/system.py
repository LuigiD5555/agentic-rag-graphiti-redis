"""Router for system management endpoints."""
import logging
from typing import Dict, Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.system.autostart_manager import AutostartManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/system", tags=["system"])


# Request/Response models
class AutostartStatus(BaseModel):
    """Autostart status response."""
    enabled: bool
    config_value: str
    config_source: str
    timestamp: str


class AutostartUpdateRequest(BaseModel):
    """Autostart update request."""
    enabled: bool


class AutostartUpdateResponse(BaseModel):
    """Autostart update response."""
    success: bool
    enabled: bool
    config_value: str
    actions: list[str]
    errors: list[str]
    timestamp: str


@router.get("/autostart", response_model=AutostartStatus)
async def get_autostart_status() -> AutostartStatus:
    """
    Get current auto-start status.
    
    Returns:
        Current auto-start configuration status
    """
    try:
        manager = AutostartManager()
        status = manager.api_get()
        return AutostartStatus(**status)
    except Exception as e:
        logger.error(f"Error getting autostart status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/autostart", response_model=AutostartUpdateResponse)
async def update_autostart_status(request: AutostartUpdateRequest) -> AutostartUpdateResponse:
    """
    Update auto-start status.
    
    Args:
        request: Autostart update request with enabled flag
        
    Returns:
        Result of the update operation
    """
    try:
        manager = AutostartManager()
        result = manager.api_set(request.enabled)
        return AutostartUpdateResponse(**result)
    except Exception as e:
        logger.error(f"Error updating autostart status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/autostart/status")
async def get_detailed_autostart_status() -> Dict[str, Any]:
    """
    Get detailed auto-start status including systemd service information.
    
    Returns:
        Detailed status information including systemd service states
    """
    try:
        manager = AutostartManager()
        status = manager.get_status()
        return status
    except Exception as e:
        logger.error(f"Error getting detailed autostart status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
