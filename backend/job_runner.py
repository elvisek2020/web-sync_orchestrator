"""
Background job runner pro asynchronní operace
"""
import asyncio
import threading
from typing import Dict, Optional, Callable
from datetime import datetime
from backend.database import JobRun, Scan, Diff, DiffItem, Batch, BatchItem, FileEntry as DBFileEntry, Dataset, JobFileStatus, JobFileStatus
from backend.storage_service import storage_service
from backend.websocket_manager import websocket_manager
from backend.adapters.factory import AdapterFactory
from backend.adapters.base import FileEntry
from backend.mount_service import mount_service

class JobRunner:
    """Spouští background joby"""
    
    def __init__(self):
        self.running_jobs: Dict[int, threading.Thread] = {}
    
    async def run_scan(self, scan_id: int, dataset_id: int):
        """Spustí scan job"""
        def scan_thread():
            session = storage_service.get_session()
            if not session:
                return
            
            try:
                scan = session.query(Scan).filter(Scan.id == scan_id).first()
                if not scan:
                    return
                
                dataset = session.query(Dataset).filter(Dataset.id == dataset_id).first()
                if not dataset:
                    scan.status = "failed"
                    try:
                        session.commit()
                    except Exception:
                        session.rollback()
                    return
                
                # Broadcast start
                asyncio.run(websocket_manager.broadcast({
                    "type": "job.started",
                    "data": {"job_id": scan_id, "type": "scan"}
                }))
                
                scan.status = "running"
                try:
                    session.commit()
                except Exception:
                    session.rollback()
                    session.commit()
                
                # Vytvoření adapteru
                adapter = AdapterFactory.create_scan_adapter(dataset, dataset.location)
                
                # Callbacky
                def progress_cb(count: int, path: str):
                    asyncio.run(websocket_manager.broadcast({
                        "type": "job.progress",
                        "data": {"job_id": scan_id, "type": "scan", "count": count, "path": path}
                    }))
                
                def log_cb(message: str):
                    asyncio.run(websocket_manager.broadcast({
                        "type": "job.log",
                        "data": {"job_id": scan_id, "type": "scan", "message": message}
                    }))
                
                # Spuštění scanu
                total_files = 0
                total_size = 0.0
                
                if log_cb:
                    log_cb(f"Starting scan for dataset {dataset_id}, roots: {dataset.roots}")
                
                try:
                    # Načtení exclude patterns (výchozí + uživatelské)
                    from backend.config import DEFAULT_EXCLUDE_PATTERNS, match_exclude_pattern
                    exclude_patterns = DEFAULT_EXCLUDE_PATTERNS.copy()
                    
                    file_iterator = adapter.list_files(dataset.roots, progress_cb, log_cb)
                    
                    for file_entry in file_iterator:
                        # Filtrování podle exclude patterns
                        if match_exclude_pattern(file_entry.full_rel_path, exclude_patterns):
                            # Přeskočit soubory, které odpovídají exclude patterns
                            continue
                        
                        # Použít merge místo add, aby se předešlo duplicitám v identity mapě
                        db_entry = DBFileEntry(
                            scan_id=scan_id,
                            full_rel_path=file_entry.full_rel_path,
                            size=file_entry.size,
                            mtime_epoch=file_entry.mtime_epoch,
                            root_rel_path=file_entry.root_rel_path
                        )
                        # Merge zajistí, že pokud objekt už existuje v session, použije se existující
                        session.merge(db_entry)
                        total_files += 1
                        total_size += file_entry.size
                        
                        # Bulk commit každých 1000 záznamů
                        if total_files % 1000 == 0:
                            try:
                                session.commit()
                            except Exception as commit_error:
                                session.rollback()
                                if log_cb:
                                    log_cb(f"Commit error: {commit_error}, retrying...")
                                session.commit()
                            if log_cb:
                                log_cb(f"Committed {total_files} files so far...")
                    
                    # Finální commit - refresh scan objektu před aktualizací
                    try:
                        session.refresh(scan)
                    except Exception:
                        # Pokud refresh selže, zkusit načíst scan znovu
                        scan = session.query(Scan).filter(Scan.id == scan_id).first()
                        if not scan:
                            raise Exception(f"Scan {scan_id} not found for final commit")
                    
                    scan.total_files = total_files
                    scan.total_size = total_size
                    scan.status = "completed"
                    
                    commit_success = False
                    try:
                        session.commit()
                        commit_success = True
                    except Exception as commit_error:
                        session.rollback()
                        if log_cb:
                            log_cb(f"Final commit error: {commit_error}, retrying...")
                        # Zkusit znovu načíst scan a aktualizovat
                        try:
                            scan = session.query(Scan).filter(Scan.id == scan_id).first()
                            if scan:
                                scan.total_files = total_files
                                scan.total_size = total_size
                                scan.status = "completed"
                                session.commit()
                                commit_success = True
                        except Exception:
                            pass
                    
                    # Pokud ani to nefunguje, použít novou session
                    if not commit_success:
                        new_session = storage_service.get_session()
                        if new_session:
                            try:
                                scan_new = new_session.query(Scan).filter(Scan.id == scan_id).first()
                                if scan_new:
                                    scan_new.total_files = total_files
                                    scan_new.total_size = total_size
                                    scan_new.status = "completed"
                                    new_session.commit()
                                    if log_cb:
                                        log_cb(f"Scan status updated using new session")
                            except Exception as e:
                                new_session.rollback()
                                if log_cb:
                                    log_cb(f"Failed to update scan status in new session: {e}")
                            finally:
                                new_session.close()
                    
                    if log_cb:
                        log_cb(f"Scan completed: {total_files} files, {total_size / 1024 / 1024:.2f} MB")
                except Exception as scan_error:
                    if log_cb:
                        log_cb(f"Error during scan iteration: {scan_error}")
                    raise
                
                # Broadcast finish - vždy poslat, i když commit selhal
                try:
                    asyncio.run(websocket_manager.broadcast({
                        "type": "job.finished",
                        "data": {"job_id": scan_id, "type": "scan", "status": "completed"}
                    }))
                except Exception as broadcast_error:
                    if log_cb:
                        log_cb(f"Failed to broadcast job.finished: {broadcast_error}")
                
            except Exception as e:
                try:
                    session.rollback()
                except:
                    pass
                scan.status = "failed"
                scan.error_message = str(e)
                try:
                    session.commit()
                except Exception as commit_error:
                    try:
                        session.rollback()
                        session.commit()
                    except Exception:
                        # Pokud ani to nefunguje, zkusit novou session
                        try:
                            new_session = storage_service.get_session()
                            if new_session:
                                scan = new_session.query(Scan).filter(Scan.id == scan_id).first()
                                if scan:
                                    scan.status = "failed"
                                    scan.error_message = str(e)
                                    new_session.commit()
                                    new_session.close()
                        except:
                            pass
                asyncio.run(websocket_manager.broadcast({
                    "type": "job.finished",
                    "data": {"job_id": scan_id, "type": "scan", "status": "failed", "error": str(e)}
                }))
            finally:
                try:
                    session.close()
                except:
                    pass
                if scan_id in self.running_jobs:
                    del self.running_jobs[scan_id]
        
        thread = threading.Thread(target=scan_thread, daemon=True)
        self.running_jobs[scan_id] = thread
        thread.start()
    
    async def run_diff(self, diff_id: int):
        """Spustí diff job"""
        def diff_thread():
            session = storage_service.get_session()
            if not session:
                return
            
            try:
                diff = session.query(Diff).filter(Diff.id == diff_id).first()
                if not diff:
                    return
                
                asyncio.run(websocket_manager.broadcast({
                    "type": "job.started",
                    "data": {"job_id": diff_id, "type": "diff"}
                }))
                
                diff.status = "running"
                session.commit()
                
                # Načtení scanů a jejich datasetů
                source_scan = session.query(Scan).filter(Scan.id == diff.source_scan_id).first()
                target_scan = session.query(Scan).filter(Scan.id == diff.target_scan_id).first()
                
                if not source_scan or not target_scan:
                    raise Exception("Source or target scan not found")
                
                source_dataset = session.query(Dataset).filter(Dataset.id == source_scan.dataset_id).first()
                target_dataset = session.query(Dataset).filter(Dataset.id == target_scan.dataset_id).first()
                
                if not source_dataset or not target_dataset:
                    raise Exception("Source or target dataset not found")
                
                # Získání root složek (měl by být jen jeden podle validace)
                source_root = source_dataset.roots[0] if source_dataset.roots else ""
                target_root = target_dataset.roots[0] if target_dataset.roots else ""
                
                # Normalizační funkce - odstraní root složku z cesty
                def normalize_path(path, root):
                    """Odstraní root složku z cesty a vrátí normalizovanou cestu"""
                    if not root:
                        return path
                    # Normalizace - odstranit úvodní lomítka
                    root_clean = root.strip("/")
                    path_clean = path.strip("/")
                    
                    # Pokud cesta začíná root složkou, odstranit ji
                    if path_clean.startswith(root_clean + "/"):
                        return path_clean[len(root_clean) + 1:]
                    elif path_clean == root_clean:
                        return ""  # Cesta je přímo root složka
                    elif path_clean.startswith(root_clean):
                        return path_clean[len(root_clean):].lstrip("/")
                    else:
                        # Pokud cesta nezačíná root, zkusit najít root v cestě
                        # Např. pokud root je "NAS-FILMY" a cesta je "NAS-FILMY/Movie/file.mkv"
                        parts = path_clean.split("/")
                        if parts[0] == root_clean:
                            return "/".join(parts[1:])
                        return path_clean
                
                # Načtení souborů s normalizovanými cestami
                source_files_raw = session.query(DBFileEntry).filter(
                    DBFileEntry.scan_id == diff.source_scan_id
                ).all()
                
                target_files_raw = session.query(DBFileEntry).filter(
                    DBFileEntry.scan_id == diff.target_scan_id
                ).all()
                
                # Vytvoření mapy normalizovaných cest -> soubory
                source_files = {}
                for f in source_files_raw:
                    normalized = normalize_path(f.full_rel_path, source_root)
                    if normalized not in source_files:
                        source_files[normalized] = f
                    # Pokud už existuje, použít první (může být duplicita)
                
                target_files = {}
                for f in target_files_raw:
                    normalized = normalize_path(f.full_rel_path, target_root)
                    if normalized not in target_files:
                        target_files[normalized] = f
                    # Pokud už existuje, použít první (může být duplicita)
                
                # Deterministické porovnání podle normalizovaných cest
                all_paths = set(source_files.keys()) | set(target_files.keys())
                total_paths = len(all_paths)
                
                # Progress feedback - start
                asyncio.run(websocket_manager.broadcast({
                    "type": "job.progress",
                    "data": {"job_id": diff_id, "type": "diff", "count": 0, "total": total_paths, "message": f"Porovnávání {total_paths} souborů..."}
                }))
                
                processed_count = 0
                for normalized_path in all_paths:
                    source_file = source_files.get(normalized_path)
                    target_file = target_files.get(normalized_path)
                    
                    if source_file and not target_file:
                        category = "missing"
                    elif source_file and target_file:
                        if source_file.size == target_file.size:
                            category = "same"
                        else:
                            category = "conflict"
                    else:
                        continue  # Soubor existuje jen v target, ignorujeme
                    
                    # Uložit normalizovanou cestu a také původní cesty pro referenci
                    diff_item = DiffItem(
                        diff_id=diff_id,
                        full_rel_path=normalized_path,  # Normalizovaná cesta pro porovnání
                        source_size=source_file.size if source_file else None,
                        target_size=target_file.size if target_file else None,
                        source_mtime=source_file.mtime_epoch if source_file else None,
                        target_mtime=target_file.mtime_epoch if target_file else None,
                        category=category
                    )
                    session.add(diff_item)
                    processed_count += 1
                    
                    # Progress feedback každých 100 souborů (častější feedback pro lepší UX)
                    if processed_count % 100 == 0:
                        asyncio.run(websocket_manager.broadcast({
                            "type": "job.progress",
                            "data": {"job_id": diff_id, "type": "diff", "count": processed_count, "total": total_paths, "message": f"Zpracováno {processed_count} / {total_paths} souborů..."}
                        }))
                    
                    # Batch commit každých 1000 záznamů pro lepší výkon (commit je dražší než progress feedback)
                    if processed_count % 1000 == 0:
                        try:
                            session.commit()
                        except Exception as commit_error:
                            session.rollback()
                            asyncio.run(websocket_manager.broadcast({
                                "type": "job.log",
                                "data": {"job_id": diff_id, "type": "diff", "message": f"Commit error: {commit_error}, retrying..."}
                            }))
                            session.commit()
                
                diff.status = "completed"
                try:
                    session.commit()
                except Exception as commit_error:
                    session.rollback()
                    asyncio.run(websocket_manager.broadcast({
                        "type": "job.log",
                        "data": {"job_id": diff_id, "type": "diff", "message": f"Final commit error: {commit_error}, retrying..."}
                    }))
                    session.commit()
                
                asyncio.run(websocket_manager.broadcast({
                    "type": "job.finished",
                    "data": {"job_id": diff_id, "type": "diff", "status": "completed"}
                }))
                
            except Exception as e:
                session.rollback()
                diff.status = "failed"
                session.commit()
                asyncio.run(websocket_manager.broadcast({
                    "type": "job.finished",
                    "data": {"job_id": diff_id, "type": "diff", "status": "failed", "error": str(e)}
                }))
            finally:
                session.close()
                if diff_id in self.running_jobs:
                    del self.running_jobs[diff_id]
        
        thread = threading.Thread(target=diff_thread, daemon=True)
        self.running_jobs[diff_id] = thread
        thread.start()
    
    async def run_batch_planning(self, batch_id: int):
        """Spustí batch planning job"""
        def batch_thread():
            session = storage_service.get_session()
            if not session:
                return
            
            try:
                batch = session.query(Batch).filter(Batch.id == batch_id).first()
                if not batch:
                    return
                
                # Broadcast start
                asyncio.run(websocket_manager.broadcast({
                    "type": "job.started",
                    "data": {"job_id": batch_id, "type": "batch"}
                }))
                
                batch.status = "running"
                session.commit()
                
                diff = session.query(Diff).filter(Diff.id == batch.diff_id).first()
                if not diff:
                    batch.status = "failed"
                    batch.error_message = "Diff not found"
                    session.commit()
                    asyncio.run(websocket_manager.broadcast({
                        "type": "job.finished",
                        "data": {"job_id": batch_id, "type": "batch", "status": "failed", "error": "Diff not found"}
                    }))
                    return
                
                # Načtení diff items
                diff_items = session.query(DiffItem).filter(
                    DiffItem.diff_id == batch.diff_id
                ).all()
                
                # Filtrování podle include_conflicts
                items_to_include = [
                    item for item in diff_items
                    if item.category == "missing" or (item.category == "conflict" and batch.include_conflicts)
                ]
                
                # Filtrování podle exclude_patterns
                from backend.config import match_exclude_pattern
                exclude_patterns = batch.exclude_patterns or []
                if exclude_patterns:
                    items_to_include = [
                        item for item in items_to_include
                        if not match_exclude_pattern(item.full_rel_path, exclude_patterns)
                    ]
                
                # Řazení od nejmenších
                items_to_include.sort(key=lambda x: x.source_size or x.target_size or 0)
                
                # Výpočet limitu USB
                import shutil
                try:
                    total, used, free = shutil.disk_usage("/mnt/usb")
                    usb_limit = int(free * (batch.usb_limit_pct / 100))
                except Exception as e:
                    usb_limit = 0
                    batch.status = "failed"
                    batch.error_message = f"Failed to get USB disk usage: {str(e)}"
                    session.commit()
                    asyncio.run(websocket_manager.broadcast({
                        "type": "job.finished",
                        "data": {"job_id": batch_id, "type": "batch", "status": "failed", "error": str(e)}
                    }))
                    return
                
                # Výběr souborů do limitu
                selected_items = []
                total_size = 0
                
                for item in items_to_include:
                    size = item.source_size or item.target_size or 0
                    if total_size + size <= usb_limit:
                        selected_items.append(item)
                        total_size += size
                    else:
                        break
                
                # Vytvoření batch items
                for item in selected_items:
                    batch_item = BatchItem(
                        batch_id=batch_id,
                        full_rel_path=item.full_rel_path,
                        size=item.source_size or item.target_size or 0,
                        category=item.category,
                        enabled=True  # Všechny soubory jsou ve výchozím stavu povolené
                    )
                    session.add(batch_item)
                
                batch.status = "ready"
                session.commit()
                
                # Broadcast success
                asyncio.run(websocket_manager.broadcast({
                    "type": "job.finished",
                    "data": {"job_id": batch_id, "type": "batch", "status": "completed"}
                }))
                
            except Exception as e:
                import traceback
                error_msg = str(e)
                traceback.print_exc()
                
                try:
                    session.rollback()
                    batch = session.query(Batch).filter(Batch.id == batch_id).first()
                    if batch:
                        batch.status = "failed"
                        batch.error_message = error_msg
                        session.commit()
                except:
                    pass
                
                asyncio.run(websocket_manager.broadcast({
                    "type": "job.finished",
                    "data": {"job_id": batch_id, "type": "batch", "status": "failed", "error": error_msg}
                }))
            finally:
                session.close()
                if batch_id in self.running_jobs:
                    del self.running_jobs[batch_id]
        
        thread = threading.Thread(target=batch_thread, daemon=True)
        self.running_jobs[batch_id] = thread
        thread.start()
    
    def run_copy(self, job_id: int, batch_id: int, direction: str, dry_run: bool = False):
        """Spustí copy job"""
        def copy_thread():
            session = storage_service.get_session()
            if not session:
                return
            
            try:
                job = session.query(JobRun).filter(JobRun.id == job_id).first()
                if not job:
                    return
                
                batch = session.query(Batch).filter(Batch.id == batch_id).first()
                if not batch:
                    job.status = "failed"
                    job.error_message = "Batch not found"
                    job.finished_at = datetime.utcnow()
                    session.commit()
                    return
                
                # Načtení diff a datasetu
                diff = session.query(Diff).filter(Diff.id == batch.diff_id).first()
                if not diff:
                    job.status = "failed"
                    job.error_message = "Diff not found"
                    job.finished_at = datetime.utcnow()
                    session.commit()
                    return
                
                source_scan = session.query(Scan).filter(Scan.id == diff.source_scan_id).first()
                if not source_scan:
                    job.status = "failed"
                    job.error_message = "Source scan not found"
                    job.finished_at = datetime.utcnow()
                    session.commit()
                    return
                
                target_scan = session.query(Scan).filter(Scan.id == diff.target_scan_id).first()
                if not target_scan:
                    job.status = "failed"
                    job.error_message = "Target scan not found"
                    job.finished_at = datetime.utcnow()
                    session.commit()
                    return
                
                source_dataset = session.query(Dataset).filter(Dataset.id == source_scan.dataset_id).first()
                if not source_dataset:
                    job.status = "failed"
                    job.error_message = "Source dataset not found"
                    job.finished_at = datetime.utcnow()
                    session.commit()
                    return
                
                target_dataset = session.query(Dataset).filter(Dataset.id == target_scan.dataset_id).first()
                if not target_dataset:
                    job.status = "failed"
                    job.error_message = "Target dataset not found"
                    job.finished_at = datetime.utcnow()
                    session.commit()
                    return
                
                # Načtení batch items (pouze povolené)
                batch_items = session.query(BatchItem).filter(
                    BatchItem.batch_id == batch_id,
                    BatchItem.enabled == True
                ).all()
                
                # Konverze na FileEntry a výpočet celkové velikosti
                file_entries = []
                total_size = 0
                for item in batch_items:
                    # Najít source file entry
                    source_file = session.query(DBFileEntry).filter(
                        DBFileEntry.scan_id == diff.source_scan_id,
                        DBFileEntry.full_rel_path == item.full_rel_path
                    ).first()
                    
                    if source_file:
                        file_entries.append(FileEntry(
                            full_rel_path=source_file.full_rel_path,
                            size=source_file.size,
                            mtime_epoch=source_file.mtime_epoch,
                            root_rel_path=source_file.root_rel_path
                        ))
                        total_size += source_file.size
                
                # Broadcast start s informacemi o batchi (pokud ještě nebyl odeslán z API)
                # API endpoint už posílá job.started, ale potřebujeme poslat i total_files a total_size
                asyncio.run(websocket_manager.broadcast({
                    "type": "job.started",
                    "data": {
                        "job_id": job_id,
                        "type": "copy",
                        "direction": direction,
                        "batch_id": batch_id,
                        "total_files": len(file_entries),
                        "total_size": total_size
                    }
                }))
                
                # Určení source a target base paths a adapterů podle konfigurace datasetů
                # USB je vždy lokální mount
                if direction == "nas1-usb":
                    # Source: NAS1 (může být lokální nebo SSH)
                    # Target: USB (vždy lokální) - vytvořit adresář s názvem jobu
                    job_dir = f"job-{job_id}"
                    if source_dataset.transfer_adapter_type == "ssh":
                        # NAS1 je přes SSH - kopírujeme z VZDÁLENÉHO na LOKÁLNÍ
                        source_base = source_dataset.transfer_adapter_config.get("base_path", "/") if source_dataset.transfer_adapter_config else "/"
                        target_base = f"/mnt/usb/{job_dir}"
                        # Vytvořit adresář na USB
                        import os
                        os.makedirs(target_base, exist_ok=True)
                        adapter = AdapterFactory.create_transfer_adapter(source_dataset)
                    else:
                        # NAS1 je lokální mount
                        source_base = "/mnt/nas1"
                        target_base = f"/mnt/usb/{job_dir}"
                        # Vytvořit adresář na USB
                        import os
                        os.makedirs(target_base, exist_ok=True)
                        from backend.adapters.local_transfer import LocalRsyncTransferAdapter
                        adapter = LocalRsyncTransferAdapter()
                        
                elif direction == "usb-nas2":
                    # Source: USB (vždy lokální) - najít adresář s názvem jobu z předchozího nas1-usb jobu
                    # Najít předchozí nas1-usb job pro stejný batch
                    from sqlalchemy import text
                    previous_job = session.query(JobRun).filter(
                        JobRun.type == "copy"
                    ).filter(
                        text("json_extract(job_metadata, '$.batch_id') = :batch_id"),
                        text("json_extract(job_metadata, '$.direction') = 'nas1-usb'")
                    ).params(batch_id=str(batch_id)).order_by(JobRun.started_at.desc()).first()
                    
                    if previous_job:
                        job_dir = f"job-{previous_job.id}"
                    else:
                        # Fallback - použít aktuální job_id (i když to není ideální)
                        job_dir = f"job-{job_id}"
                    
                    source_base = f"/mnt/usb/{job_dir}"
                    if target_dataset.transfer_adapter_type == "ssh":
                        # NAS2 je přes SSH - kopírujeme z LOKÁLNÍHO na VZDÁLENÝ
                        target_base = target_dataset.transfer_adapter_config.get("base_path", "/") if target_dataset.transfer_adapter_config else "/"
                        adapter = AdapterFactory.create_transfer_adapter(target_dataset)
                    else:
                        # NAS2 je lokální mount
                        target_base = "/mnt/nas2"
                        from backend.adapters.local_transfer import LocalRsyncTransferAdapter
                        adapter = LocalRsyncTransferAdapter()
                else:
                    raise ValueError(f"Unknown direction: {direction}")
                
                # Callbacky pro progress
                total_files = len(file_entries)
                copied_count = 0
                copied_size = 0
                processed_files = set()  # Sledovat už zpracované soubory pro správné počítání velikosti
                log_messages = []  # Ukládat log zprávy
                file_statuses = []  # Ukládat stav každého souboru
                
                def progress_cb(count: int, path: str, file_size: int = 0, success: bool = True, error: str = None):
                    nonlocal copied_count, copied_size
                    copied_count = count
                    # Přidat velikost jen jednou pro každý soubor
                    if file_size > 0 and path not in processed_files:
                        copied_size += file_size
                        processed_files.add(path)
                        # Uložit stav souboru
                        file_statuses.append({
                            "file_path": path,
                            "file_size": file_size,
                            "status": "copied" if success else "failed",
                            "error_message": error
                        })
                    asyncio.run(websocket_manager.broadcast({
                        "type": "job.progress",
                        "data": {
                            "job_id": job_id,
                            "type": "copy",
                            "batch_id": batch_id,
                            "count": count,
                            "total_files": total_files,
                            "current_file": path,
                            "current_file_size": file_size,
                            "copied_size": copied_size,
                            "total_size": total_size
                        }
                    }))
                
                def log_cb(message: str):
                    nonlocal log_messages
                    log_messages.append(message)
                    asyncio.run(websocket_manager.broadcast({
                        "type": "job.log",
                        "data": {"job_id": job_id, "type": "copy", "message": message}
                    }))
                
                # Spuštění kopírování
                # Pro SSH adapter předáme source_is_remote parametr, pokud je potřeba
                from backend.adapters.ssh_transfer import SshRsyncTransferAdapter
                if isinstance(adapter, SshRsyncTransferAdapter) and direction == "nas1-usb":
                    # SSH adapter pro nas1-usb - source je vzdálený
                    result = adapter.send_batch(
                        file_entries,
                        source_base,
                        target_base,
                        dry_run=dry_run,
                        progress_cb=progress_cb,
                        log_cb=log_cb,
                        source_is_remote=True
                    )
                elif isinstance(adapter, SshRsyncTransferAdapter) and direction == "usb-nas2":
                    # SSH adapter pro usb-nas2 - target je vzdálený (source_is_remote=False je default)
                    result = adapter.send_batch(
                        file_entries,
                        source_base,
                        target_base,
                        dry_run=dry_run,
                        progress_cb=progress_cb,
                        log_cb=log_cb,
                        source_is_remote=False
                    )
                else:
                    # Lokální adapter nebo default SSH chování
                    result = adapter.send_batch(
                        file_entries,
                        source_base,
                        target_base,
                        dry_run=dry_run,
                        progress_cb=progress_cb,
                        log_cb=log_cb
                    )
                
                # Uložit stav každého souboru do databáze
                for file_status in file_statuses:
                    file_status_record = JobFileStatus(
                        job_id=job_id,
                        file_path=file_status["file_path"],
                        file_size=file_status["file_size"],
                        status=file_status["status"],
                        error_message=file_status.get("error_message"),
                        copied_at=datetime.utcnow() if file_status["status"] == "copied" else None
                    )
                    session.add(file_status_record)
                
                # Aktualizace jobu
                job.status = "completed" if result.get("success") else "failed"
                job.finished_at = datetime.utcnow()
                if not result.get("success"):
                    job.error_message = result.get("error", "Unknown error")
                # Uložit log zprávy
                if log_messages:
                    job.job_log = "\n".join(log_messages)
                
                # Aktualizace batch statusu
                batch.status = "completed" if result.get("success") else "failed"
                
                try:
                    session.commit()
                except Exception as commit_error:
                    session.rollback()
                    if log_cb:
                        log_cb(f"Commit error: {commit_error}, retrying...")
                    try:
                        session.commit()
                    except Exception:
                        session.rollback()
                        raise
                
                # Broadcast finish
                asyncio.run(websocket_manager.broadcast({
                    "type": "job.finished",
                    "data": {
                        "job_id": job_id,
                        "type": "copy",
                        "status": job.status,
                        "files_copied": result.get("files_copied", 0)
                    }
                }))
                
            except Exception as e:
                session.rollback()
                # Znovu načíst job a batch pro aktualizaci
                job = session.query(JobRun).filter(JobRun.id == job_id).first()
                batch = session.query(Batch).filter(Batch.id == batch_id).first()
                if job:
                    job.status = "failed"
                    job.error_message = str(e)
                    job.finished_at = datetime.utcnow()
                if batch:
                    batch.status = "failed"
                try:
                    session.commit()
                except Exception:
                    session.rollback()
                asyncio.run(websocket_manager.broadcast({
                    "type": "job.finished",
                    "data": {"job_id": job_id, "type": "copy", "status": "failed", "batch_id": batch_id, "error": str(e)}
                }))
            finally:
                session.close()
                if job_id in self.running_jobs:
                    del self.running_jobs[job_id]

        thread = threading.Thread(target=copy_thread, daemon=True)
        self.running_jobs[job_id] = thread
        thread.start()

job_runner = JobRunner()
