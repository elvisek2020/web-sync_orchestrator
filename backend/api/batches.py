"""
Batch API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

from backend.storage_service import storage_service
from backend.database import Batch, BatchItem, Diff
from backend.mount_service import mount_service

router = APIRouter()

class BatchCreate(BaseModel):
    diff_id: int
    include_conflicts: bool = False
    exclude_patterns: Optional[List[str]] = None  # Seznam patternů pro výjimky

class BatchResponse(BaseModel):
    id: int
    diff_id: int
    created_at: datetime
    usb_limit_pct: float
    include_conflicts: bool
    exclude_patterns: Optional[List[str]] = None
    status: str
    
    model_config = {"from_attributes": True}

class BatchItemResponse(BaseModel):
    id: int
    batch_id: int
    full_rel_path: str
    size: int
    category: str
    enabled: Optional[bool] = True
    
    model_config = {"from_attributes": True}

class BatchSummary(BaseModel):
    total_files: int
    total_size: int
    usb_available: int
    usb_limit: int  # Pro kompatibilitu, ale vždy = usb_available (100%)

async def check_safe_mode():
    """Dependency - kontroluje SAFE MODE"""
    mount_status = await mount_service.get_status()
    if mount_status.get("safe_mode", True):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SAFE MODE: USB/DB unavailable"
        )

@router.post("/", response_model=BatchResponse)
async def create_batch(batch_data: BatchCreate, _: None = Depends(check_safe_mode)):
    """Vytvořit batch z diffu"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        # Ověření diffu
        diff = session.query(Diff).filter(Diff.id == batch_data.diff_id).first()
        if not diff:
            raise HTTPException(status_code=404, detail="Diff not found")
        
        # Kombinace výchozích výjimek a uživatelských výjimek
        from backend.config import DEFAULT_EXCLUDE_PATTERNS
        exclude_patterns = list(DEFAULT_EXCLUDE_PATTERNS)
        if batch_data.exclude_patterns:
            exclude_patterns.extend(batch_data.exclude_patterns)
        # Odstranit duplicity
        exclude_patterns = list(dict.fromkeys(exclude_patterns))
        
        # Vytvoření batch záznamu
        batch = Batch(
            diff_id=batch_data.diff_id,
            usb_limit_pct=100.0,  # Vždy použít 100% - USB limit % byl odstraněn
            include_conflicts=batch_data.include_conflicts,
            exclude_patterns=exclude_patterns,
            status="pending"
        )
        session.add(batch)
        session.commit()
        session.refresh(batch)
        
        # Spustit background job pro batch planning
        from backend.job_runner import job_runner
        import asyncio
        asyncio.create_task(job_runner.run_batch_planning(batch.id))
        
        return BatchResponse.model_validate(batch)
    finally:
        session.close()

@router.get("/", response_model=List[BatchResponse])
async def list_batches():
    """Seznam všech batchů"""
    session = storage_service.get_session()
    if not session:
        return []
    
    try:
        batches = session.query(Batch).order_by(Batch.created_at.desc()).all()
        return [BatchResponse.model_validate(b) for b in batches]
    finally:
        session.close()

@router.get("/{batch_id}", response_model=BatchResponse)
async def get_batch(batch_id: int):
    """Detail batchu"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        batch = session.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")
        return BatchResponse.model_validate(batch)
    finally:
        session.close()

@router.get("/{batch_id}/items", response_model=List[BatchItemResponse])
async def get_batch_items(batch_id: int, skip: int = 0, limit: int = 100):
    """Položky batchu"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        items = session.query(BatchItem).filter(
            BatchItem.batch_id == batch_id
        ).offset(skip).limit(limit).all()
        return [BatchItemResponse.model_validate(i) for i in items]
    finally:
        session.close()

@router.get("/{batch_id}/summary", response_model=BatchSummary)
async def get_batch_summary(batch_id: int):
    """Shrnutí batchu"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        batch = session.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")
        
        # Počítat jen povolené (enabled) soubory
        items = session.query(BatchItem).filter(
            BatchItem.batch_id == batch_id,
            BatchItem.enabled == True
        ).all()
        
        total_size = sum(item.size for item in items)
        
        # Získat skutečnou dostupnou kapacitu USB
        import shutil
        usb_path = "/mnt/usb"
        try:
            total, used, free = shutil.disk_usage(usb_path)
            usb_available = free
        except:
            usb_available = 0
        
        return BatchSummary(
            total_files=len(items),
            total_size=total_size,
            usb_available=usb_available,
            usb_limit=usb_available  # USB limit je nyní stejný jako dostupná kapacita (100%)
        )
    finally:
        session.close()

@router.delete("/{batch_id}")
async def delete_batch(batch_id: int, _: None = Depends(check_safe_mode)):
    """Smazat batch a všechny jeho položky"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        batch = session.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")
        
        # Smazat všechny položky batchu
        session.query(BatchItem).filter(BatchItem.batch_id == batch_id).delete()
        
        # Smazat batch
        session.delete(batch)
        session.commit()
        
        return {"message": "Batch deleted"}
    finally:
        session.close()

@router.put("/{batch_id}/items/{item_id}/enabled")
async def toggle_batch_item_enabled(batch_id: int, item_id: int, enabled: bool, _: None = Depends(check_safe_mode)):
    """Povolit/zakázat konkrétní soubor v batchi"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        item = session.query(BatchItem).filter(
            BatchItem.id == item_id,
            BatchItem.batch_id == batch_id
        ).first()
        
        if not item:
            raise HTTPException(status_code=404, detail="Batch item not found")
        
        item.enabled = enabled
        session.commit()
        return {"message": "Batch item updated", "enabled": enabled}
    finally:
        session.close()

@router.put("/{batch_id}/items/toggle-all")
async def toggle_all_batch_items(batch_id: int, enabled: bool, _: None = Depends(check_safe_mode)):
    """Povolit/zakázat všechny soubory v batchi najednou"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        items = session.query(BatchItem).filter(BatchItem.batch_id == batch_id).all()
        if not items:
            raise HTTPException(status_code=404, detail="No batch items found")
        
        for item in items:
            item.enabled = enabled
        
        session.commit()
        return {"message": f"All batch items {'enabled' if enabled else 'disabled'}", "count": len(items)}
    finally:
        session.close()

