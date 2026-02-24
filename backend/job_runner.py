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
        self._lock = threading.Lock()
    
    def _register_job(self, job_id: int, thread: threading.Thread):
        with self._lock:
            self.running_jobs[job_id] = thread
    
    def _unregister_job(self, job_id: int):
        with self._lock:
            self.running_jobs.pop(job_id, None)
    
    def _is_job_alive(self, job_id: int) -> bool:
        with self._lock:
            thread = self.running_jobs.get(job_id)
            return thread is not None and thread.is_alive()
    
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
                
                # Zkontrolovat, zda scan už není dokončený nebo běžící (ochrana proti duplicitnímu spuštění)
                if scan.status in ["completed", "running"]:
                    if self._is_job_alive(scan_id):
                        return
                    # Pokud není v running_jobs, ale status je running, resetovat na pending
                    if scan.status == "running":
                        scan.status = "pending"
                        try:
                            session.commit()
                        except Exception:
                            session.rollback()
                            session.commit()
                
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
                
                # Callbacky – log_cb also accumulates messages for DB storage
                scan_log_lines = []

                def progress_cb(count: int, path: str):
                    asyncio.run(websocket_manager.broadcast({
                        "type": "job.progress",
                        "data": {"job_id": scan_id, "type": "scan", "count": count, "path": path}
                    }))
                
                def log_cb(message: str):
                    scan_log_lines.append(message)
                    asyncio.run(websocket_manager.broadcast({
                        "type": "job.log",
                        "data": {"job_id": scan_id, "type": "scan", "message": message}
                    }))
                
                # Spuštění scanu – dedicated sqlite3 connection for bulk inserts
                import sqlite3
                total_files = 0
                total_size = 0.0
                BATCH_SIZE = 500
                batch_buffer = []
                commit_failures = 0
                records_lost = 0
                iteration_completed = False
                
                if log_cb:
                    log_cb(f"Starting scan for dataset {dataset_id}, roots: {dataset.roots}")
                
                db_path = storage_service.db_path
                bulk_conn = sqlite3.connect(db_path, timeout=30)
                bulk_conn.execute("PRAGMA journal_mode=WAL")
                bulk_conn.execute("PRAGMA synchronous=NORMAL")
                bulk_conn.execute("PRAGMA busy_timeout=10000")
                INSERT_SQL = "INSERT INTO file_entries (scan_id, full_rel_path, size, mtime_epoch, root_rel_path) VALUES (?, ?, ?, ?, ?)"
                
                def _flush_batch(force_msg=None):
                    """Flush batch_buffer to DB via dedicated sqlite3 connection with retry."""
                    nonlocal batch_buffer, commit_failures, records_lost
                    if not batch_buffer:
                        return
                    rows = batch_buffer
                    batch_buffer = []
                    for attempt in range(3):
                        try:
                            bulk_conn.executemany(INSERT_SQL, rows)
                            bulk_conn.commit()
                            if force_msg and log_cb:
                                log_cb(force_msg)
                            return
                        except Exception as e:
                            try:
                                bulk_conn.rollback()
                            except Exception:
                                pass
                            if attempt < 2:
                                if log_cb:
                                    log_cb(f"WARNING: Batch insert attempt {attempt+1} failed ({e}), retrying...")
                                import time
                                time.sleep(0.5)
                            else:
                                commit_failures += 1
                                records_lost += len(rows)
                                if log_cb:
                                    log_cb(f"ERROR: Batch insert failed after 3 attempts, {len(rows)} records LOST: {e}")
                
                try:
                    from backend.config import DEFAULT_EXCLUDE_PATTERNS, match_exclude_pattern
                    exclude_patterns = DEFAULT_EXCLUDE_PATTERNS.copy()
                    
                    file_iterator = adapter.list_files(dataset.roots, progress_cb, log_cb)
                    
                    for file_entry in file_iterator:
                        if match_exclude_pattern(file_entry.full_rel_path, exclude_patterns):
                            continue
                        
                        batch_buffer.append((
                            scan_id,
                            file_entry.full_rel_path,
                            file_entry.size,
                            file_entry.mtime_epoch,
                            file_entry.root_rel_path,
                        ))
                        total_files += 1
                        total_size += file_entry.size
                        
                        if len(batch_buffer) >= BATCH_SIZE:
                            _flush_batch(f"Committed {total_files} files so far...")
                    
                    # Final batch
                    _flush_batch(f"Final batch committed, {total_files} files total")
                    
                    iteration_completed = True
                    
                    # Close dedicated bulk connection
                    try:
                        bulk_conn.close()
                    except Exception:
                        pass
                    
                    # Verify actual DB record count via fresh sqlite3 connection
                    verify_conn = sqlite3.connect(db_path, timeout=10)
                    db_count = verify_conn.execute(
                        "SELECT COUNT(*) FROM file_entries WHERE scan_id = ?", (scan_id,)
                    ).fetchone()[0]
                    verify_conn.close()
                    
                    if log_cb:
                        log_cb(f"DB verification: counter={total_files}, db_records={db_count}, lost={records_lost}, commit_failures={commit_failures}")
                    
                    if db_count != total_files:
                        if log_cb:
                            log_cb(f"WARNING: DB mismatch ({db_count} != {total_files}), diff={db_count - total_files}")
                    
                    # Update scan status
                    try:
                        session.refresh(scan)
                    except Exception:
                        scan = session.query(Scan).filter(Scan.id == scan_id).first()
                        if not scan:
                            raise Exception(f"Scan {scan_id} not found for final update")
                    
                    scan.total_files = db_count
                    scan.total_size = total_size
                    scan.status = "completed"
                    scan.error_message = "\n".join(scan_log_lines[-500:]) if scan_log_lines else None
                    
                    commit_success = False
                    for attempt in range(3):
                        try:
                            session.commit()
                            commit_success = True
                            break
                        except Exception as e:
                            session.rollback()
                            if log_cb:
                                log_cb(f"WARNING: Status commit attempt {attempt+1} failed: {e}")
                            try:
                                scan = session.query(Scan).filter(Scan.id == scan_id).first()
                                if scan:
                                    scan.total_files = db_count
                                    scan.total_size = total_size
                                    scan.status = "completed"
                                    scan.error_message = "\n".join(scan_log_lines[-500:]) if scan_log_lines else None
                            except Exception:
                                pass
                    
                    if not commit_success:
                        new_session = storage_service.get_session()
                        if new_session:
                            try:
                                s = new_session.query(Scan).filter(Scan.id == scan_id).first()
                                if s:
                                    s.total_files = db_count
                                    s.total_size = total_size
                                    s.status = "completed"
                                    s.error_message = "\n".join(scan_log_lines[-500:]) if scan_log_lines else None
                                    new_session.commit()
                                    commit_success = True
                            except Exception:
                                new_session.rollback()
                            finally:
                                new_session.close()
                    
                    if log_cb:
                        log_cb(f"Scan completed: {db_count} files in DB (scanned {total_files}), {total_size / 1024 / 1024:.2f} MB, lost={records_lost}")
                    
                    broadcast_status = "completed" if commit_success else "failed"
                    try:
                        asyncio.run(websocket_manager.broadcast({
                            "type": "job.finished",
                            "data": {
                                "job_id": scan_id,
                                "type": "scan",
                                "status": broadcast_status,
                                "error": None if commit_success else "Failed to commit scan status"
                            }
                        }))
                    except Exception as broadcast_error:
                        if log_cb:
                            log_cb(f"Failed to broadcast job.finished: {broadcast_error}")
                except Exception as scan_error:
                    try:
                        bulk_conn.close()
                    except Exception:
                        pass
                    if log_cb:
                        log_cb(f"Error during scan: {scan_error}")
                    if not iteration_completed:
                        raise
                
            except Exception as e:
                try:
                    bulk_conn.close()
                except Exception:
                    pass
                try:
                    session.rollback()
                except:
                    pass
                scan.status = "failed"
                log_with_error = scan_log_lines + [f"FATAL: {e}"]
                scan.error_message = "\n".join(log_with_error[-500:])
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
                self._unregister_job(scan_id)
        
        thread = threading.Thread(target=scan_thread, daemon=True)
        self._register_job(scan_id, thread)
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
                
                from backend.utils import normalize_path, normalize_root_rel_path, is_ignored_path
                
                # Načtení souborů s normalizovanými cestami
                # Zkusit načíst soubory s ošetřením poškozené databáze
                try:
                    source_files_raw = session.query(DBFileEntry).filter(
                        DBFileEntry.scan_id == diff.source_scan_id
                    ).all()
                except Exception as query_error:
                    # Pokud selže query, může to být poškozená databáze
                    if "malformed" in str(query_error).lower() or "database disk image" in str(query_error).lower():
                        raise Exception(f"Databáze je poškozená - nelze načíst soubory ze scanu {diff.source_scan_id}. "
                                      f"Zkontrolujte integritu databáze nebo obnovte ze zálohy.")
                    raise
                
                try:
                    target_files_raw = session.query(DBFileEntry).filter(
                        DBFileEntry.scan_id == diff.target_scan_id
                    ).all()
                except Exception as query_error:
                    # Pokud selže query, může to být poškozená databáze
                    if "malformed" in str(query_error).lower() or "database disk image" in str(query_error).lower():
                        raise Exception(f"Databáze je poškozená - nelze načíst soubory ze scanu {diff.target_scan_id}. "
                                      f"Zkontrolujte integritu databáze nebo obnovte ze zálohy.")
                    raise
                
                # Debug: Logování root složek pro diagnostiku
                import logging
                logger = logging.getLogger(__name__)
                source_root = source_dataset.roots[0] if source_dataset.roots else ""
                target_root = target_dataset.roots[0] if target_dataset.roots else ""
                logger.info(f"Diff {diff_id}: Source dataset root: '{source_root}', Target dataset root: '{target_root}'")
                logger.info(f"Diff {diff_id}: Source files count: {len(source_files_raw)}, Target files count: {len(target_files_raw)}")
                
                # Vytvoření mapy normalizovaných cest -> soubory
                # Použijeme root_rel_path z každého souboru místo root z datasetu pro přesnější normalizaci
                source_files = {}  # normalizovaná cesta -> soubor
                source_files_by_original = {}  # původní cesta -> soubor (pro fallback)
                normalization_issues = []  # Pro debug - ukládání problémů s normalizací
                
                for f in source_files_raw:
                    if not f.full_rel_path or is_ignored_path(f.full_rel_path):
                        continue
                    file_root = normalize_root_rel_path(f.root_rel_path) if f.root_rel_path else ""
                    if not file_root:
                        file_root = normalize_root_rel_path(source_dataset.roots[0]) if source_dataset.roots else ""
                    
                    normalized = normalize_path(f.full_rel_path, file_root)
                    if is_ignored_path(normalized):
                        continue
                    if normalized not in source_files:
                        source_files[normalized] = f
                    # Uložit také do mapy původních cest pro fallback
                    source_files_by_original[f.full_rel_path] = f
                    # Debug: Zkontrolovat, zda normalizace funguje správně
                    if len(normalization_issues) < 5 and f.full_rel_path and file_root:
                        # Uložit několik příkladů pro debug
                        if not normalized or (normalized == f.full_rel_path and file_root):
                            normalization_issues.append(f"Source: path='{f.full_rel_path}', root='{file_root}', normalized='{normalized}'")
                
                target_files = {}  # normalizovaná cesta -> soubor
                target_files_by_original = {}  # původní cesta -> soubor (pro fallback)
                for f in target_files_raw:
                    if not f.full_rel_path or is_ignored_path(f.full_rel_path):
                        continue
                    file_root = normalize_root_rel_path(f.root_rel_path) if f.root_rel_path else ""
                    if not file_root:
                        file_root = normalize_root_rel_path(target_dataset.roots[0]) if target_dataset.roots else ""
                    
                    normalized = normalize_path(f.full_rel_path, file_root)
                    if is_ignored_path(normalized):
                        continue
                    if normalized not in target_files:
                        target_files[normalized] = f
                    # Uložit také do mapy původních cest pro fallback
                    target_files_by_original[f.full_rel_path] = f
                    # Debug: Zkontrolovat, zda normalizace funguje správně
                    if len(normalization_issues) < 10 and f.full_rel_path and file_root:
                        # Uložit několik příkladů pro debug
                        if not normalized or (normalized == f.full_rel_path and file_root):
                            normalization_issues.append(f"Target: path='{f.full_rel_path}', root='{file_root}', normalized='{normalized}'")
                
                # Debug: Logovat problémy s normalizací
                if normalization_issues:
                    logger.warning(f"Diff {diff_id}: Potential normalization issues (showing first 10):")
                    for issue in normalization_issues[:10]:
                        logger.warning(f"  {issue}")
                
                logger.info(f"Diff {diff_id}: Normalized source files: {len(source_files)}, Normalized target files: {len(target_files)}")
                
                # Deterministické porovnání podle normalizovaných cest
                all_paths = set(source_files.keys()) | set(target_files.keys())
                total_paths = len(all_paths)
                
                # Debug: Zkontrolovat několik příkladů normalizovaných cest
                if total_paths > 0:
                    sample_paths = list(all_paths)[:5]
                    logger.info(f"Diff {diff_id}: Sample normalized paths: {sample_paths}")
                
                # Progress feedback - start
                asyncio.run(websocket_manager.broadcast({
                    "type": "job.progress",
                    "data": {"job_id": diff_id, "type": "diff", "count": 0, "total": total_paths, "message": f"Porovnávání {total_paths} souborů..."}
                }))
                
                processed_count = 0
                matched_by_fallback = 0  # Počítadlo pro debug
                for normalized_path in all_paths:
                    source_file = source_files.get(normalized_path)
                    target_file = target_files.get(normalized_path)
                    
                    # Fallback: Pokud normalizace selhala, zkusit najít soubor pomocí alternativního porovnání
                    if source_file and not target_file:
                        # Zkusit najít soubor v target pomocí původní cesty nebo jiné normalizace
                        # Toto může pomoci, pokud normalizace selhala kvůli rozdílným root složkám
                        found_by_fallback = False
                        if source_file.full_rel_path in target_files_by_original:
                            target_file = target_files_by_original[source_file.full_rel_path]
                            found_by_fallback = True
                            matched_by_fallback += 1
                            logger.debug(f"Diff {diff_id}: Found match by fallback for '{normalized_path}' (original: '{source_file.full_rel_path}')")
                        elif normalized_path in target_files_by_original:
                            # Zkusit najít pomocí normalizované cesty jako klíče v původních cestách
                            target_file = target_files_by_original.get(normalized_path)
                            if target_file:
                                found_by_fallback = True
                                matched_by_fallback += 1
                        
                        if not target_file:
                            category = "missing"
                        else:
                            # Soubor byl nalezen pomocí fallback, pokračovat s porovnáním
                            pass
                    elif source_file and target_file:
                        # Soubor byl nalezen normálně
                        pass
                    else:
                        # Soubor existuje jen v target - označit jako "extra"
                        pass
                    
                    if source_file and target_file:
                        if source_file.size != target_file.size:
                            category = "conflict"
                        elif (source_file.mtime_epoch and target_file.mtime_epoch and
                              abs(source_file.mtime_epoch - target_file.mtime_epoch) > 2):
                            category = "conflict"
                        else:
                            category = "same"
                    elif source_file and not target_file:
                        category = "missing"
                    else:
                        category = "extra"
                    
                    diff_item = DiffItem(
                        diff_id=diff_id,
                        full_rel_path=normalized_path,
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
                
                # Debug: Logovat výsledky fallback logiky
                if matched_by_fallback > 0:
                    logger.info(f"Diff {diff_id}: Matched {matched_by_fallback} files using fallback logic")
                
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
                import traceback
                from sqlalchemy.exc import DatabaseError
                
                # Detekce poškozené databáze
                is_database_corrupted = False
                error_str = str(e).lower()
                
                # Zkontrolovat, zda je to DatabaseError s malformed
                if isinstance(e, DatabaseError) and "malformed" in error_str:
                    is_database_corrupted = True
                # Zkontrolovat, zda chybová zpráva obsahuje indikátory poškozené databáze
                elif "database disk image is malformed" in error_str:
                    is_database_corrupted = True
                elif "malformed" in error_str and "database" in error_str:
                    is_database_corrupted = True
                # Zkontrolovat, zda je to naše vlastní výjimka o poškozené databázi
                elif "databáze je poškozená" in error_str or "database is corrupted" in error_str:
                    is_database_corrupted = True
                
                error_traceback = traceback.format_exc()
                if is_database_corrupted:
                    error_msg = f"POŠKOZENÁ DATABÁZE: Databáze je poškozená a nelze z ní číst data.\n\n"
                    error_msg += f"Možné příčiny:\n"
                    error_msg += f"- Nečisté ukončení aplikace\n"
                    error_msg += f"- Problémy s USB diskem (odpojení během zápisu)\n"
                    error_msg += f"- Chyby filesystemu\n\n"
                    error_msg += f"Doporučené řešení:\n"
                    error_msg += f"1. Zkontrolujte USB disk (fsck, kontrola chyb)\n"
                    error_msg += f"2. Obnovte databázi ze zálohy (pokud máte)\n"
                    error_msg += f"3. Vytvořte novou databázi (data budou ztracena)\n\n"
                    error_msg += f"Původní chyba: {str(e)}"
                else:
                    error_msg = f"{str(e)}\n\nTraceback:\n{error_traceback}"
                
                try:
                    session.rollback()
                except:
                    pass
                
                # Zkusit aktualizovat diff v aktuální session
                try:
                    # Refresh diff objektu
                    try:
                        session.refresh(diff)
                    except:
                        diff = session.query(Diff).filter(Diff.id == diff_id).first()
                        if not diff:
                            raise Exception(f"Diff {diff_id} not found for error update")
                    
                    diff.status = "failed"
                    diff.error_message = error_msg
                    session.commit()
                except Exception as commit_error:
                    try:
                        session.rollback()
                        # Zkusit znovu
                        diff = session.query(Diff).filter(Diff.id == diff_id).first()
                        if diff:
                            diff.status = "failed"
                            diff.error_message = error_msg
                            session.commit()
                    except Exception:
                        # Pokud ani to nefunguje, zkusit novou session
                        try:
                            new_session = storage_service.get_session()
                            if new_session:
                                diff = new_session.query(Diff).filter(Diff.id == diff_id).first()
                                if diff:
                                    diff.status = "failed"
                                    diff.error_message = error_msg
                                    new_session.commit()
                                    new_session.close()
                        except Exception as final_error:
                            import logging
                            logging.getLogger(__name__).error(f"Failed to update diff error message: {final_error}")
                
                # Broadcast s chybou
                try:
                    asyncio.run(websocket_manager.broadcast({
                        "type": "job.finished",
                        "data": {"job_id": diff_id, "type": "diff", "status": "failed", "error": str(e)}
                    }))
                except Exception as broadcast_error:
                    import logging
                    logging.getLogger(__name__).error(f"Failed to broadcast diff error: {broadcast_error}")
            finally:
                session.close()
                self._unregister_job(diff_id)
        
        thread = threading.Thread(target=diff_thread, daemon=True)
        self._register_job(diff_id, thread)
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
                
                total_items = len(diff_items)
                
                # Progress feedback - start
                asyncio.run(websocket_manager.broadcast({
                    "type": "job.progress",
                    "data": {"job_id": batch_id, "type": "batch", "count": 0, "total": total_items, "message": f"Načítání {total_items} položek z porovnání..."}
                }))
                
                # Filtrování podle kategorií
                items_to_include = [
                    item for item in diff_items
                    if item.category == "missing"
                    or (item.category == "conflict" and batch.include_conflicts)
                    or (item.category == "extra" and batch.include_extra)
                ]
                
                # Progress feedback - po filtrování
                asyncio.run(websocket_manager.broadcast({
                    "type": "job.progress",
                    "data": {"job_id": batch_id, "type": "batch", "count": len(items_to_include), "total": total_items, "message": f"Filtrování podle kategorií: {len(items_to_include)} položek..."}
                }))
                
                # Filtrování podle exclude_patterns
                from backend.config import match_exclude_pattern
                exclude_patterns = batch.exclude_patterns or []
                if exclude_patterns:
                    items_before_exclude = len(items_to_include)
                    items_to_include = [
                        item for item in items_to_include
                        if not match_exclude_pattern(item.full_rel_path, exclude_patterns)
                    ]
                    # Progress feedback - po exclude patterns
                    asyncio.run(websocket_manager.broadcast({
                        "type": "job.progress",
                        "data": {"job_id": batch_id, "type": "batch", "count": len(items_to_include), "total": total_items, "message": f"Filtrování podle výjimek: {len(items_to_include)} položek (odfiltrováno {items_before_exclude - len(items_to_include)})..."}
                    }))
                
                # Řazení od nejmenších
                items_to_include.sort(key=lambda x: x.source_size or x.target_size or 0)
                
                # Výpočet dostupné kapacity USB (pro informaci, ale neomezujeme)
                import shutil
                try:
                    total, used, free = shutil.disk_usage("/mnt/usb")
                    usb_available = free
                except Exception as e:
                    usb_available = 0
                    # Neoznačujeme jako failed, jen logujeme
                    asyncio.run(websocket_manager.broadcast({
                        "type": "job.log",
                        "data": {"job_id": batch_id, "type": "batch", "message": f"Warning: Failed to get USB disk usage: {str(e)}"}
                    }))
                
                # Vzít všechny soubory (bez limitu)
                selected_items = items_to_include
                total_size = sum(item.source_size or item.target_size or 0 for item in selected_items)
                processed_count = len(selected_items)
                
                # Progress feedback - před vytvářením batch items
                asyncio.run(websocket_manager.broadcast({
                    "type": "job.progress",
                    "data": {"job_id": batch_id, "type": "batch", "count": len(selected_items), "total": len(items_to_include), "message": f"Vytváření plánu: {len(selected_items)} souborů..."}
                }))
                
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
                
                batch.status = "ready_to_phase_2"
                session.commit()
                
                # Broadcast success
                asyncio.run(websocket_manager.broadcast({
                    "type": "job.finished",
                    "data": {"job_id": batch_id, "type": "batch", "status": "ready"}
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
                self._unregister_job(batch_id)
        
        thread = threading.Thread(target=batch_thread, daemon=True)
        self._register_job(batch_id, thread)
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
                
                from backend.utils import normalize_path, normalize_root_rel_path
                
                source_root = normalize_root_rel_path(source_dataset.roots[0]) if source_dataset.roots else ""
                target_root = normalize_root_rel_path(target_dataset.roots[0]) if target_dataset.roots else ""
                
                # Načtení batch items (pouze povolené)
                batch_items = session.query(BatchItem).filter(
                    BatchItem.batch_id == batch_id,
                    BatchItem.enabled == True
                ).all()
                
                if not batch_items:
                    job.status = "failed"
                    job.error_message = "Žádné povolené soubory v plánu"
                    job.finished_at = datetime.utcnow()
                    session.commit()
                    asyncio.run(websocket_manager.broadcast({
                        "type": "job.finished",
                        "data": {"job_id": job_id, "type": "copy", "status": "failed", "error": "Žádné povolené soubory v plánu"}
                    }))
                    return
                
                # Načtení všech source file entries a vytvoření mapy normalizovaných cest -> soubory
                source_files_raw = session.query(DBFileEntry).filter(
                    DBFileEntry.scan_id == diff.source_scan_id
                ).all()
                
                # Vytvoření mapy normalizovaných cest -> soubory (stejně jako v run_diff)
                source_files_map = {}
                for f in source_files_raw:
                    normalized = normalize_path(f.full_rel_path, source_root)
                    if normalized not in source_files_map:
                        source_files_map[normalized] = f
                    # Pokud už existuje, použít první (může být duplicita)
                
                # Konverze na FileEntry a výpočet celkové velikosti
                file_entries = []
                total_size = 0
                missing_files = []
                for item in batch_items:
                    # item.full_rel_path je normalizovaná cesta (z DiffItem)
                    # Najít source file entry pomocí normalizované cesty
                    source_file = source_files_map.get(item.full_rel_path)
                    
                    if source_file:
                        # Použít normalizovanou cestu (bez root) pro rsync
                        # item.full_rel_path je už normalizovaná cesta (bez root složky)
                        file_entries.append(FileEntry(
                            full_rel_path=item.full_rel_path,  # Normalizovaná cesta bez root
                            size=source_file.size,
                            mtime_epoch=source_file.mtime_epoch,
                            root_rel_path=source_file.root_rel_path
                        ))
                        total_size += source_file.size
                    else:
                        missing_files.append(item.full_rel_path)
                
                if not file_entries:
                    error_msg = f"Žádné soubory k kopírování. Nenalezeno {len(missing_files)} souborů v scanu."
                    if missing_files:
                        error_msg += f" První chybějící: {missing_files[0]}"
                    job.status = "failed"
                    job.error_message = error_msg
                    job.finished_at = datetime.utcnow()
                    session.commit()
                    asyncio.run(websocket_manager.broadcast({
                        "type": "job.finished",
                        "data": {"job_id": job_id, "type": "copy", "status": "failed", "error": error_msg}
                    }))
                    return
                
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
                
                # Inicializace proměnných pro logování a progress
                log_messages = []  # Ukládat log zprávy
                file_statuses = []  # Ukládat stav každého souboru
                copied_count = 0
                copied_size = 0
                processed_files = set()  # Sledovat už zpracované soubory pro správné počítání velikosti
                
                # Definovat log_cb před použitím
                def log_cb(message: str):
                    nonlocal log_messages
                    log_messages.append(message)
                    asyncio.run(websocket_manager.broadcast({
                        "type": "job.log",
                        "data": {"job_id": job_id, "type": "copy", "message": message}
                    }))
                
                # Určení source a target base paths a adapterů podle konfigurace datasetů
                # USB je vždy lokální mount
                # source_root je root složka datasetu (např. "NAS-POHADKY-SERIALY")
                if direction == "nas1-usb":
                    # Source: NAS1 (může být lokální nebo SSH)
                    # Target: USB (vždy lokální) - vytvořit adresář s názvem jobu
                    # Použít job_id parametr - to je ID jobu, který spustil kopírování
                    job_dir = f"job-{job_id}"
                    log_cb(f"Creating job directory: {job_dir} (job_id: {job_id})")
                    if source_dataset.transfer_adapter_type == "ssh":
                        # NAS1 je přes SSH - kopírujeme z VZDÁLENÉHO na LOKÁLNÍ
                        base_path = source_dataset.transfer_adapter_config.get("base_path", "/") if source_dataset.transfer_adapter_config else "/"
                        # Přidat root složku k base_path
                        if source_root:
                            source_base = f"{base_path.rstrip('/')}/{source_root}" if base_path != "/" else f"/{source_root}"
                        else:
                            source_base = base_path
                        target_base = f"/mnt/usb/{job_dir}"
                        # Vytvořit adresář na USB
                        import os
                        os.makedirs(target_base, exist_ok=True)
                        adapter = AdapterFactory.create_transfer_adapter(source_dataset)
                    else:
                        # NAS1 je lokální mount
                        # Přidat root složku k mount pointu
                        if source_root:
                            source_base = f"/mnt/nas1/{source_root}"
                        else:
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
                        # Použít ID předchozího jobu, který vytvořil adresář
                        job_dir = f"job-{previous_job.id}"
                        log_cb(f"Using previous job directory: {job_dir} (previous_job.id: {previous_job.id})")
                    else:
                        # Fallback - použít job_id parametr (ID jobu, který spustil kopírování)
                        job_dir = f"job-{job_id}"
                        log_cb(f"Using current job directory (fallback): {job_dir} (job_id: {job_id})")
                    
                    source_base = f"/mnt/usb/{job_dir}"
                    if target_dataset.transfer_adapter_type == "ssh":
                        # NAS2 je přes SSH - kopírujeme z LOKÁLNÍHO na VZDÁLENÝ
                        base_path = target_dataset.transfer_adapter_config.get("base_path", "/") if target_dataset.transfer_adapter_config else "/"
                        # Přidat root složku k base_path
                        if target_root:
                            target_base = f"{base_path.rstrip('/')}/{target_root}" if base_path != "/" else f"/{target_root}"
                        else:
                            target_base = base_path
                        adapter = AdapterFactory.create_transfer_adapter(target_dataset)
                    else:
                        # NAS2 je lokální mount
                        # Přidat root složku k mount pointu
                        if target_root:
                            target_base = f"/mnt/nas2/{target_root}"
                        else:
                            target_base = "/mnt/nas2"
                        from backend.adapters.local_transfer import LocalRsyncTransferAdapter
                        adapter = LocalRsyncTransferAdapter()
                else:
                    raise ValueError(f"Unknown direction: {direction}")
                
                # Callbacky pro progress
                total_files = len(file_entries)
                
                def progress_cb(count: int, path: str, file_size: int = 0, success: bool = True, error: str = None):
                    nonlocal copied_count, copied_size
                    # count je počet zkopírovaných souborů z adapteru
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
                    # Broadcast progress - použít copied_count (aktuální počet zkopírovaných souborů)
                    asyncio.run(websocket_manager.broadcast({
                        "type": "job.progress",
                        "data": {
                            "job_id": job_id,
                            "type": "copy",
                            "batch_id": batch_id,
                            "count": copied_count,  # Použít copied_count místo count
                            "total_files": total_files,
                            "current_file": path,
                            "current_file_size": file_size,
                            "copied_size": copied_size,
                            "total_size": total_size
                        }
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
                
                # Aktualizace batch statusu podle směru kopírování
                if direction == "nas1-usb":
                    # Po dokončení fáze 2 (NAS → USB) je batch ready pro fázi 3
                    batch.status = "ready_to_phase_3" if result.get("success") else "failed"
                elif direction == "usb-nas2":
                    # Po dokončení fáze 3 (USB → NAS) je batch completed
                    batch.status = "completed" if result.get("success") else "failed"
                else:
                    batch.status = "failed"
                
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
                self._unregister_job(job_id)

        thread = threading.Thread(target=copy_thread, daemon=True)
        self._register_job(job_id, thread)
        thread.start()

    def verify_copy(self, job_id: int) -> dict:
        """Verify that files from a completed copy job exist at the target with correct sizes.
        
        Returns a dict with verification results (synchronous, not threaded).
        """
        import os
        session = storage_service.get_session()
        if not session:
            return {"success": False, "error": "Database unavailable"}

        try:
            job = session.query(JobRun).filter(JobRun.id == job_id).first()
            if not job:
                return {"success": False, "error": "Job not found"}
            if job.type != "copy":
                return {"success": False, "error": "Not a copy job"}

            metadata = job.job_metadata or {}
            batch_id = metadata.get("batch_id")
            direction = metadata.get("direction")
            if not batch_id or not direction:
                return {"success": False, "error": "Missing job metadata"}

            batch = session.query(Batch).filter(Batch.id == batch_id).first()
            if not batch:
                return {"success": False, "error": "Batch not found"}

            diff = session.query(Diff).filter(Diff.id == batch.diff_id).first()
            if not diff:
                return {"success": False, "error": "Diff not found"}

            source_scan = session.query(Scan).filter(Scan.id == diff.source_scan_id).first()
            target_scan = session.query(Scan).filter(Scan.id == diff.target_scan_id).first()
            source_dataset = session.query(Dataset).filter(Dataset.id == source_scan.dataset_id).first() if source_scan else None
            target_dataset = session.query(Dataset).filter(Dataset.id == target_scan.dataset_id).first() if target_scan else None

            if not source_dataset or not target_dataset:
                return {"success": False, "error": "Dataset not found"}

            # Determine the target base path
            from backend.utils import normalize_root_rel_path
            source_root = normalize_root_rel_path(source_dataset.roots[0]) if source_dataset.roots else ""
            target_root = normalize_root_rel_path(target_dataset.roots[0]) if target_dataset.roots else ""

            if direction == "nas1-usb":
                target_base = f"/mnt/usb/job-{job_id}"
            elif direction == "usb-nas2":
                if target_root:
                    target_base = f"/mnt/nas2/{target_root}"
                else:
                    target_base = "/mnt/nas2"
            else:
                return {"success": False, "error": f"Unknown direction: {direction}"}

            # Load file statuses from the job
            file_statuses = session.query(JobFileStatus).filter(
                JobFileStatus.job_id == job_id
            ).all()

            if not file_statuses:
                # Fallback: use batch items
                batch_items = session.query(BatchItem).filter(
                    BatchItem.batch_id == batch_id,
                    BatchItem.enabled == True
                ).all()
                files_to_check = [(bi.full_rel_path, bi.size) for bi in batch_items]
            else:
                files_to_check = [(fs.file_path, fs.file_size) for fs in file_statuses if fs.status == "copied"]

            verified = 0
            missing = []
            size_mismatch = []

            for file_path, expected_size in files_to_check:
                full_path = os.path.join(target_base, file_path)
                if not os.path.exists(full_path):
                    missing.append(file_path)
                else:
                    actual_size = os.path.getsize(full_path)
                    if actual_size != expected_size:
                        size_mismatch.append({
                            "path": file_path,
                            "expected": expected_size,
                            "actual": actual_size
                        })
                    else:
                        verified += 1

            total = len(files_to_check)
            return {
                "success": True,
                "total_files": total,
                "verified_ok": verified,
                "missing_count": len(missing),
                "missing_files": missing[:50],
                "size_mismatch_count": len(size_mismatch),
                "size_mismatch_files": size_mismatch[:50],
                "target_base": target_base,
                "direction": direction
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
        finally:
            session.close()


job_runner = JobRunner()
