"""
Scan API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status, Response
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import csv
import io

from backend.storage_service import storage_service
from backend.database import Scan, FileEntry, Dataset
from backend.mount_service import mount_service

router = APIRouter()

class ScanCreate(BaseModel):
    dataset_id: int

class ScanResponse(BaseModel):
    id: int
    dataset_id: int
    created_at: datetime
    status: str
    total_files: int
    total_size: float
    error_message: Optional[str] = None
    
    model_config = {"from_attributes": True}

class FileEntryResponse(BaseModel):
    id: int
    scan_id: int
    full_rel_path: str
    size: int
    mtime_epoch: float
    root_rel_path: str
    
    model_config = {"from_attributes": True}

async def check_safe_mode():
    """Dependency - kontroluje SAFE MODE"""
    mount_status = await mount_service.get_status()
    if mount_status.get("safe_mode", True):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SAFE MODE: USB/DB unavailable"
        )

@router.post("/", response_model=ScanResponse)
async def create_scan(scan_data: ScanCreate, _: None = Depends(check_safe_mode)):
    """Spustit nový scan"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        # Ověření datasetu
        dataset = session.query(Dataset).filter(Dataset.id == scan_data.dataset_id).first()
        if not dataset:
            raise HTTPException(status_code=404, detail="Dataset not found")
        
        # Vytvoření scan záznamu
        scan = Scan(
            dataset_id=scan_data.dataset_id,
            status="pending"
        )
        session.add(scan)
        session.commit()
        session.refresh(scan)
        
        # Spustit background job pro scan
        from backend.job_runner import job_runner
        import asyncio
        asyncio.create_task(job_runner.run_scan(scan.id, scan_data.dataset_id))
        
        return ScanResponse.model_validate(scan)
    finally:
        session.close()

@router.get("/", response_model=List[ScanResponse])
async def list_scans():
    """Seznam všech scanů"""
    session = storage_service.get_session()
    if not session:
        return []
    
    try:
        scans = session.query(Scan).order_by(Scan.created_at.desc()).all()
        return [ScanResponse.model_validate(s) for s in scans]
    finally:
        session.close()

@router.get("/{scan_id}", response_model=ScanResponse)
async def get_scan(scan_id: int):
    """Detail scanu"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        scan = session.query(Scan).filter(Scan.id == scan_id).first()
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        return ScanResponse.model_validate(scan)
    finally:
        session.close()

@router.get("/{scan_id}/files", response_model=List[FileEntryResponse])
async def get_scan_files(scan_id: int, skip: int = 0, limit: int = 100):
    """Soubory ve scanu"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        files = session.query(FileEntry).filter(
            FileEntry.scan_id == scan_id
        ).offset(skip).limit(limit).all()
        return [FileEntryResponse.model_validate(f) for f in files]
    finally:
        session.close()

@router.get("/{scan_id}/export")
async def export_scan_csv(scan_id: int):
    """Export scanu do CSV"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        scan = session.query(Scan).filter(Scan.id == scan_id).first()
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        
        # Načíst všechny soubory ve scanu
        files = session.query(FileEntry).filter(
            FileEntry.scan_id == scan_id
        ).order_by(FileEntry.full_rel_path).all()
        
        # Vytvořit CSV v paměti
        output = io.StringIO()
        writer = csv.writer(output)
        
        # Hlavička
        writer.writerow(['Cesta', 'Velikost (B)', 'Velikost (GB)', 'Datum změny'])
        
        # Data
        for file in files:
            size_gb = (file.size / 1024 / 1024 / 1024) if file.size else 0
            mtime_str = datetime.fromtimestamp(file.mtime_epoch).strftime('%Y-%m-%d %H:%M:%S') if file.mtime_epoch else ''
            writer.writerow([
                file.full_rel_path,
                file.size,
                f"{size_gb:.6f}",
                mtime_str
            ])
        
        # Vrátit CSV jako response
        csv_content = output.getvalue()
        output.close()
        
        return Response(
            content=csv_content,
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename=scan_{scan_id}_export.csv"
            }
        )
    finally:
        session.close()

@router.delete("/{scan_id}")
async def delete_scan(scan_id: int, _: None = Depends(check_safe_mode)):
    """Smazat scan a všechny jeho soubory"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        scan = session.query(Scan).filter(Scan.id == scan_id).first()
        if not scan:
            raise HTTPException(status_code=404, detail="Scan not found")
        
        # Smazat všechny soubory ve scanu
        session.query(FileEntry).filter(FileEntry.scan_id == scan_id).delete()
        
        # Smazat scan
        session.delete(scan)
        session.commit()
        
        return {"message": "Scan deleted"}
    finally:
        session.close()

