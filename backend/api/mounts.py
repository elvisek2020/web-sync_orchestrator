"""
Mount status API - whitelisted v SAFE MODE
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Dict, Optional
from backend.mount_service import mount_service

router = APIRouter()

class MountStatus(BaseModel):
    available: bool
    path: str
    writable: bool
    error: Optional[str] = None
    total_size: int = 0
    used_size: int = 0
    free_size: int = 0

class MountsStatusResponse(BaseModel):
    nas1: MountStatus
    usb: MountStatus
    nas2: MountStatus
    safe_mode: bool

@router.get("/status")
async def get_mounts_status():
    """Získat stav všech mountů - whitelisted v SAFE MODE"""
    status = await mount_service.get_status()
    return MountsStatusResponse(
        nas1=MountStatus(**status["nas1"]),
        usb=MountStatus(**status["usb"]),
        nas2=MountStatus(**status["nas2"]),
        safe_mode=status["safe_mode"]
    )

@router.post("/status/refresh")
async def refresh_mounts_status():
    """Manuální refresh stavu mountů"""
    await mount_service.check_mounts()
    return await get_mounts_status()

