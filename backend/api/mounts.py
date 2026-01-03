"""
Mount status API - whitelisted v SAFE MODE
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Dict, Optional
from backend.mount_service import mount_service
from backend.storage_service import storage_service

router = APIRouter()

class MountStatus(BaseModel):
    available: bool
    path: str
    writable: bool
    error: Optional[str] = None
    total_size: int = 0
    used_size: int = 0
    free_size: int = 0

class DatabaseStatus(BaseModel):
    available: bool
    db_path: Optional[str] = None
    error: Optional[str] = None

class MountsStatusResponse(BaseModel):
    nas1: MountStatus
    usb: MountStatus
    nas2: MountStatus
    safe_mode: bool
    database: DatabaseStatus

@router.get("/status")
async def get_mounts_status():
    """Získat stav všech mountů a databáze - whitelisted v SAFE MODE"""
    status = await mount_service.get_status()
    
    # Stav databáze
    db_status = DatabaseStatus(
        available=storage_service.available,
        db_path=storage_service.db_path,
        error=None if storage_service.available else "Database not available"
    )
    
    return MountsStatusResponse(
        nas1=MountStatus(**status["nas1"]),
        usb=MountStatus(**status["usb"]),
        nas2=MountStatus(**status["nas2"]),
        safe_mode=status["safe_mode"],
        database=db_status
    )

@router.post("/status/refresh")
async def refresh_mounts_status():
    """Manuální refresh stavu mountů"""
    await mount_service.check_mounts()
    return await get_mounts_status()

