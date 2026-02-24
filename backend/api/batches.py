"""
Batch API endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import PlainTextResponse
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
    include_extra: bool = False
    exclude_patterns: Optional[List[str]] = None

class BatchResponse(BaseModel):
    id: int
    diff_id: int
    created_at: datetime
    usb_limit_pct: float
    include_conflicts: bool
    include_extra: bool = False
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
            usb_limit_pct=100.0,
            include_conflicts=batch_data.include_conflicts,
            include_extra=batch_data.include_extra,
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

@router.get("/{batch_id}/script")
async def generate_copy_script(batch_id: int, direction: str = "nas-to-usb"):
    """Generate an interactive bash script that handles missing/conflict/extra items."""
    session = storage_service.get_session()
    if not session:
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        batch = session.query(Batch).filter(Batch.id == batch_id).first()
        if not batch:
            raise HTTPException(status_code=404, detail="Batch not found")

        items = session.query(BatchItem).filter(
            BatchItem.batch_id == batch_id,
            BatchItem.enabled == True
        ).order_by(BatchItem.full_rel_path).all()

        if not items:
            raise HTTPException(status_code=404, detail="No enabled files in batch")

        if direction == "usb-to-nas":
            default_src = "/mnt/usb"
            default_dst = "/mnt/nas2"
            dir_label = "USB → NAS"
        else:
            default_src = "/mnt/nas1"
            default_dst = "/mnt/usb"
            dir_label = "NAS → USB"

        missing = [i for i in items if i.category == "missing"]
        conflict = [i for i in items if i.category == "conflict"]
        extra = [i for i in items if i.category == "extra"]

        def file_array(name, file_list):
            if not file_list:
                return f"{name}=()"
            entries = "\n".join(f'  "{item.full_rel_path}"' for item in file_list)
            return f"{name}=(\n{entries}\n)"

        def size_gb(file_list):
            return sum(i.size for i in file_list) / (1024 ** 3)

        total_size_gb = size_gb(items)
        show_extra = direction == "usb-to-nas" and len(extra) > 0

        script = f'''#!/usr/bin/env bash
# ============================================================
# Sync script – Batch #{batch_id} ({dir_label})
# Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
# ============================================================
#
# Usage:
#   bash sync_batch_{batch_id}.sh <source_root> <dest_root>
#
# Example:
#   bash sync_batch_{batch_id}.sh {default_src} {default_dst}
#
# ============================================================

set -euo pipefail

SRC="${{1:?"Usage: $0 <source_root> <dest_root>"}}"
DST="${{2:?"Usage: $0 <source_root> <dest_root>"}}"
SRC="${{SRC%/}}"
DST="${{DST%/}}"

[ ! -d "$SRC" ] && echo "ERROR: Source not found: $SRC" && exit 1
[ ! -d "$DST" ] && echo "ERROR: Dest not found: $DST" && exit 1

# ---- File lists by category ----
{file_array("MISSING_FILES", missing)}

{file_array("CONFLICT_FILES", conflict)}

{file_array("EXTRA_FILES", extra)}

# ---- Summary ----
echo "========================================"
echo "  Batch #{batch_id} – {dir_label}"
echo "  Source: $SRC"
echo "  Dest:   $DST"
echo "========================================"
echo ""
echo "  Kategorie:"
echo "    1) Chybí:     ${{#MISSING_FILES[@]}} souborů ({size_gb(missing):.2f} GB) → kopírovat na cíl"
echo "    2) Konflikty: ${{#CONFLICT_FILES[@]}} souborů ({size_gb(conflict):.2f} GB) → přepsat na cíli"'''

        if show_extra:
            script += f'''
echo "    3) Přebývá:   ${{#EXTRA_FILES[@]}} souborů ({size_gb(extra):.2f} GB) → smazat z cíle"'''

        script += f'''
echo ""

# ---- Interactive menu ----
DO_MISSING="y"
DO_CONFLICT="y"
DO_EXTRA="n"

if [ ${{#MISSING_FILES[@]}} -gt 0 ]; then
  read -p "  Kopírovat chybějící (${{#MISSING_FILES[@]}})? [A/n]: " ans
  [[ "$ans" =~ ^[nN] ]] && DO_MISSING="n"
fi

if [ ${{#CONFLICT_FILES[@]}} -gt 0 ]; then
  read -p "  Přepsat konflikty (${{#CONFLICT_FILES[@]}})? [A/n]: " ans
  [[ "$ans" =~ ^[nN] ]] && DO_CONFLICT="n"
fi'''

        if show_extra:
            script += f'''

if [ ${{#EXTRA_FILES[@]}} -gt 0 ]; then
  read -p "  Smazat přebývající (${{#EXTRA_FILES[@]}})? [a/N]: " ans
  [[ "$ans" =~ ^[aAyY] ]] && DO_EXTRA="y"
fi'''

        script += '''

echo ""
echo "========================================"

COPIED=0
OVERWRITTEN=0
DELETED=0
FAILED=0
FAILED_LIST=()

# ---- Copy missing files ----
if [ "$DO_MISSING" = "y" ] && [ ${#MISSING_FILES[@]} -gt 0 ]; then
  echo ""
  echo ">> Kopíruji chybějící soubory..."
  IDX=0
  for FILE in "${MISSING_FILES[@]}"; do
    IDX=$((IDX + 1))
    SRC_PATH="${SRC}/${FILE}"
    DST_PATH="${DST}/${FILE}"
    printf "  [%d/%d] %s ... " "$IDX" "${#MISSING_FILES[@]}" "$FILE"
    if [ ! -f "$SRC_PATH" ]; then
      echo "SKIP (source not found)"
      FAILED=$((FAILED + 1))
      FAILED_LIST+=("COPY: $FILE (source not found)")
      continue
    fi
    mkdir -p "$(dirname "$DST_PATH")"
    if rsync -a --inplace "$SRC_PATH" "$DST_PATH" 2>/dev/null; then
      echo "OK"
      COPIED=$((COPIED + 1))
    else
      echo "FAILED"
      FAILED=$((FAILED + 1))
      FAILED_LIST+=("COPY: $FILE")
    fi
  done
fi

# ---- Overwrite conflict files ----
if [ "$DO_CONFLICT" = "y" ] && [ ${#CONFLICT_FILES[@]} -gt 0 ]; then
  echo ""
  echo ">> Přepisuji konflikty..."
  IDX=0
  for FILE in "${CONFLICT_FILES[@]}"; do
    IDX=$((IDX + 1))
    SRC_PATH="${SRC}/${FILE}"
    DST_PATH="${DST}/${FILE}"
    printf "  [%d/%d] %s ... " "$IDX" "${#CONFLICT_FILES[@]}" "$FILE"
    if [ ! -f "$SRC_PATH" ]; then
      echo "SKIP (source not found)"
      FAILED=$((FAILED + 1))
      FAILED_LIST+=("OVERWRITE: $FILE (source not found)")
      continue
    fi
    mkdir -p "$(dirname "$DST_PATH")"
    if rsync -a --inplace "$SRC_PATH" "$DST_PATH" 2>/dev/null; then
      echo "OK"
      OVERWRITTEN=$((OVERWRITTEN + 1))
    else
      echo "FAILED"
      FAILED=$((FAILED + 1))
      FAILED_LIST+=("OVERWRITE: $FILE")
    fi
  done
fi

# ---- Delete extra files ----
if [ "$DO_EXTRA" = "y" ] && [ ${#EXTRA_FILES[@]} -gt 0 ]; then
  echo ""
  echo ">> Mažu přebývající soubory..."
  IDX=0
  for FILE in "${EXTRA_FILES[@]}"; do
    IDX=$((IDX + 1))
    DST_PATH="${DST}/${FILE}"
    printf "  [%d/%d] %s ... " "$IDX" "${#EXTRA_FILES[@]}" "$FILE"
    if [ ! -f "$DST_PATH" ]; then
      echo "SKIP (not found)"
      continue
    fi
    if rm -f "$DST_PATH" 2>/dev/null; then
      echo "DELETED"
      DELETED=$((DELETED + 1))
      # Clean up empty parent directories
      DIR=$(dirname "$DST_PATH")
      while [ "$DIR" != "$DST" ] && [ -d "$DIR" ] && [ -z "$(ls -A "$DIR" 2>/dev/null)" ]; do
        rmdir "$DIR" 2>/dev/null || break
        DIR=$(dirname "$DIR")
      done
    else
      echo "FAILED"
      FAILED=$((FAILED + 1))
      FAILED_LIST+=("DELETE: $FILE")
    fi
  done
fi

# ---- Final summary ----
echo ""
echo "========================================"
echo "  Hotovo!"
echo "    Zkopírováno:  $COPIED"
echo "    Přepsáno:     $OVERWRITTEN"
echo "    Smazáno:      $DELETED"
echo "    Chyby:        $FAILED"
echo "========================================"

if [ $FAILED -gt 0 ]; then
  echo ""
  echo "  Chybné soubory:"
  for F in "${FAILED_LIST[@]}"; do
    echo "    - $F"
  done
  exit 1
fi
'''

        filename = f"sync_batch_{batch_id}.sh"
        return PlainTextResponse(
            content=script,
            media_type="application/x-sh",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
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

