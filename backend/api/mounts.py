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
    import logging
    logger = logging.getLogger(__name__)
    
    status = await mount_service.get_status()
    
    # Stav databáze s detailním logováním
    db_available = storage_service.available
    db_path = storage_service.db_path
    has_session_local = storage_service.SessionLocal is not None
    has_engine = storage_service.engine is not None
    
    # Logování pro debugging
    logger.info(f"Database status check: available={db_available}, db_path={db_path}, has_session_local={has_session_local}, has_engine={has_engine}")
    
    # Zjistit důvod nedostupnosti
    error_msg = None
    if not db_available:
        reasons = []
        if not db_path:
            reasons.append("db_path is None")
        if not has_engine:
            reasons.append("engine is None")
        if not has_session_local:
            reasons.append("SessionLocal is None")
        if status.get("safe_mode", True):
            reasons.append("SAFE MODE is active")
        if not status.get("usb", {}).get("available", False):
            reasons.append("USB mount not available")
        if not status.get("usb", {}).get("writable", False):
            reasons.append("USB mount not writable")
        
        error_msg = f"Database not available. Reasons: {', '.join(reasons) if reasons else 'unknown'}"
        logger.warning(f"Database unavailable: {error_msg}")
    
    db_status = DatabaseStatus(
        available=db_available,
        db_path=db_path,
        error=error_msg
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

