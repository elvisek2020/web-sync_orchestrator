"""
Diff API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

from backend.storage_service import storage_service
from backend.database import Diff, DiffItem, Scan
from backend.mount_service import mount_service

router = APIRouter()

class DiffCreate(BaseModel):
    source_scan_id: int
    target_scan_id: int

class DiffResponse(BaseModel):
    id: int
    source_scan_id: int
    target_scan_id: int
    created_at: datetime
    status: str
    error_message: Optional[str] = None
    
    model_config = {"from_attributes": True}

class DiffItemResponse(BaseModel):
    id: int
    diff_id: int
    full_rel_path: str
    source_size: Optional[int]
    target_size: Optional[int]
    source_mtime: Optional[float]
    target_mtime: Optional[float]
    category: str
    
    model_config = {"from_attributes": True}

class DiffSummary(BaseModel):
    total_files: int
    missing_count: int
    missing_size: int
    same_count: int
    same_size: int
    conflict_count: int
    conflict_size: int

async def check_safe_mode():
    """Dependency - kontroluje SAFE MODE"""
    mount_status = await mount_service.get_status()
    if mount_status.get("safe_mode", True):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SAFE MODE: USB/DB unavailable"
        )

@router.post("/", response_model=DiffResponse)
async def create_diff(diff_data: DiffCreate, _: None = Depends(check_safe_mode)):
    """Spustit nový diff"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        # Ověření scanů
        source_scan = session.query(Scan).filter(Scan.id == diff_data.source_scan_id).first()
        target_scan = session.query(Scan).filter(Scan.id == diff_data.target_scan_id).first()
        
        if not source_scan or not target_scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        
        # Vytvoření diff záznamu
        diff = Diff(
            source_scan_id=diff_data.source_scan_id,
            target_scan_id=diff_data.target_scan_id,
            status="pending"
        )
        session.add(diff)
        session.commit()
        session.refresh(diff)
        
        # Spustit background job pro diff
        from backend.job_runner import job_runner
        import asyncio
        asyncio.create_task(job_runner.run_diff(diff.id))
        
        return DiffResponse.model_validate(diff)
    finally:
        session.close()

@router.get("/", response_model=List[DiffResponse])
async def list_diffs():
    """Seznam všech diffů"""
    session = storage_service.get_session()
    if not session:
        return []
    
    try:
        diffs = session.query(Diff).order_by(Diff.created_at.desc()).all()
        return [DiffResponse.model_validate(d) for d in diffs]
    finally:
        session.close()

@router.get("/{diff_id}", response_model=DiffResponse)
async def get_diff(diff_id: int):
    """Detail diffu"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        diff = session.query(Diff).filter(Diff.id == diff_id).first()
        if not diff:
            raise HTTPException(status_code=404, detail="Diff not found")
        return DiffResponse.model_validate(diff)
    finally:
        session.close()

@router.get("/{diff_id}/items", response_model=List[DiffItemResponse])
async def get_diff_items(diff_id: int, skip: int = 0, limit: int = 100):
    """Položky diffu"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        items = session.query(DiffItem).filter(
            DiffItem.diff_id == diff_id
        ).offset(skip).limit(limit).all()
        return [DiffItemResponse.model_validate(i) for i in items]
    finally:
        session.close()

@router.get("/{diff_id}/summary", response_model=DiffSummary)
async def get_diff_summary(diff_id: int):
    """Shrnutí diffu"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        items = session.query(DiffItem).filter(DiffItem.diff_id == diff_id).all()
        
        summary = DiffSummary(
            total_files=len(items),
            missing_count=0,
            missing_size=0,
            same_count=0,
            same_size=0,
            conflict_count=0,
            conflict_size=0
        )
        
        for item in items:
            size = item.source_size or item.target_size or 0
            if item.category == "missing":
                summary.missing_count += 1
                summary.missing_size += size
            elif item.category == "same":
                summary.same_count += 1
                summary.same_size += size
            elif item.category == "conflict":
                summary.conflict_count += 1
                summary.conflict_size += size
        
        return summary
    finally:
        session.close()

@router.delete("/{diff_id}")
async def delete_diff(diff_id: int, _: None = Depends(check_safe_mode)):
    """Smazat diff a všechny jeho položky"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        diff = session.query(Diff).filter(Diff.id == diff_id).first()
        if not diff:
            raise HTTPException(status_code=404, detail="Diff not found")
        
        # Smazat všechny položky diffu
        session.query(DiffItem).filter(DiffItem.diff_id == diff_id).delete()
        
        # Smazat diff
        session.delete(diff)
        session.commit()
        
        return {"message": "Diff deleted"}
    finally:
        session.close()

