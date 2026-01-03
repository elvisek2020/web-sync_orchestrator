"""
Copy (Transfer) API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

from backend.storage_service import storage_service
from backend.database import JobRun, Batch, Diff, Scan, Dataset
from backend.mount_service import mount_service

router = APIRouter()

class CopyRequest(BaseModel):
    batch_id: int
    dry_run: bool = False

class JobRunResponse(BaseModel):
    id: int
    type: str
    status: str
    started_at: datetime
    finished_at: Optional[datetime]
    error_message: Optional[str]
    job_metadata: Optional[dict]
    
    model_config = {"from_attributes": True}

async def check_safe_mode():
    """Dependency - kontroluje SAFE MODE"""
    mount_status = await mount_service.get_status()
    if mount_status.get("safe_mode", True):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SAFE MODE: USB/DB unavailable"
        )

@router.post("/nas1-usb")
async def copy_nas1_to_usb(request: CopyRequest, _: None = Depends(check_safe_mode)):
    """Kopírovat z NAS1 na USB (NAS1 režim)"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        # Ověření batchu
        batch = session.query(Batch).filter(Batch.id == request.batch_id).first()
        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")
        
        # Načtení diff a datasetů pro kontrolu, jestli se používá SSH
        diff = session.query(Diff).filter(Diff.id == batch.diff_id).first()
        if not diff:
            raise HTTPException(status_code=404, detail="Diff not found")
        
        source_scan = session.query(Scan).filter(Scan.id == diff.source_scan_id).first()
        if not source_scan:
            raise HTTPException(status_code=404, detail="Source scan not found")
        
        source_dataset = session.query(Dataset).filter(Dataset.id == source_scan.dataset_id).first()
        if not source_dataset:
            raise HTTPException(status_code=404, detail="Source dataset not found")
        
        # Ověření mountů
        mount_status = await mount_service.get_status()
        # NAS1 mount kontrolujeme jen pokud se nepoužívá SSH adapter
        if source_dataset.transfer_adapter_type != "ssh" and not mount_status["nas1"]["available"]:
            raise HTTPException(status_code=503, detail="NAS1 not available")
        # USB je vždy lokální, takže vždy kontrolujeme
        if not mount_status["usb"]["available"]:
            raise HTTPException(status_code=503, detail="USB not available")
        
        # Vytvoření job run záznamu
        job = JobRun(
            type="copy",
            status="running",
            job_metadata={"batch_id": request.batch_id, "direction": "nas1-usb", "dry_run": request.dry_run}
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        
        # Spustit background job pro copy (job.started se pošle z job_runner s kompletními informacemi)
        from backend.job_runner import job_runner
        job_runner.run_copy(job.id, request.batch_id, "nas1-usb", request.dry_run)
        
        return JobRunResponse.model_validate(job)
    finally:
        session.close()

@router.post("/usb-nas2")
async def copy_usb_to_nas2(request: CopyRequest, _: None = Depends(check_safe_mode)):
    """Kopírovat z USB na NAS2 (MAC režim)"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        # Ověření batchu
        batch = session.query(Batch).filter(Batch.id == request.batch_id).first()
        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")
        
        # Načtení diff a datasetů pro kontrolu, jestli se používá SSH
        diff = session.query(Diff).filter(Diff.id == batch.diff_id).first()
        if not diff:
            raise HTTPException(status_code=404, detail="Diff not found")
        
        target_scan = session.query(Scan).filter(Scan.id == diff.target_scan_id).first()
        if not target_scan:
            raise HTTPException(status_code=404, detail="Target scan not found")
        
        target_dataset = session.query(Dataset).filter(Dataset.id == target_scan.dataset_id).first()
        if not target_dataset:
            raise HTTPException(status_code=404, detail="Target dataset not found")
        
        # Ověření mountů
        mount_status = await mount_service.get_status()
        # USB je vždy lokální, takže vždy kontrolujeme
        if not mount_status["usb"]["available"]:
            raise HTTPException(status_code=503, detail="USB not available")
        # NAS2 mount kontrolujeme jen pokud se nepoužívá SSH adapter
        if target_dataset.transfer_adapter_type != "ssh" and not mount_status["nas2"]["available"]:
            raise HTTPException(status_code=503, detail="NAS2 not available")
        
        # Vytvoření job run záznamu
        job = JobRun(
            type="copy",
            status="running",
            job_metadata={"batch_id": request.batch_id, "direction": "usb-nas2", "dry_run": request.dry_run}
        )
        session.add(job)
        session.commit()
        session.refresh(job)
        
        # Spustit background job pro copy (job.started se pošle z job_runner s kompletními informacemi)
        from backend.job_runner import job_runner
        job_runner.run_copy(job.id, request.batch_id, "usb-nas2", request.dry_run)
        
        return JobRunResponse.model_validate(job)
    finally:
        session.close()

@router.get("/jobs", response_model=List[JobRunResponse])
async def list_jobs():
    """Seznam všech copy jobů"""
    session = storage_service.get_session()
    if not session:
        return []
    
    try:
        jobs = session.query(JobRun).filter(
            JobRun.type == "copy"
        ).order_by(JobRun.started_at.desc()).all()
        return [JobRunResponse.model_validate(j) for j in jobs]
    finally:
        session.close()

@router.get("/jobs/{job_id}", response_model=JobRunResponse)
async def get_job(job_id: int):
    """Detail copy jobu"""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")
    
    try:
        job = session.query(JobRun).filter(JobRun.id == job_id).first()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return JobRunResponse.model_validate(job)
    finally:
        session.close()

