"""
Local filesystem scan adapter
"""
import os
from typing import Iterator, List, Optional, Callable
from backend.adapters.base import ScanAdapter, FileEntry

class LocalScanAdapter(ScanAdapter):
    """Scan adapter pro lokální filesystem"""
    
    def __init__(self, base_path: str):
        self.base_path = base_path
    
    def list_files(
        self,
        roots: List[str],
        progress_cb: Optional[Callable[[int, str], None]] = None,
        log_cb: Optional[Callable[[str], None]] = None
    ) -> Iterator[FileEntry]:
        """Listuje soubory pomocí os.walk"""
        count = 0
        
        for root_rel in roots:
            root_abs = os.path.join(self.base_path, root_rel)
            
            if not os.path.exists(root_abs):
                if log_cb:
                    log_cb(f"Warning: Root path does not exist: {root_abs}")
                continue
            
            if not os.path.isdir(root_abs):
                if log_cb:
                    log_cb(f"Warning: Root path is not a directory: {root_abs}")
                continue
            
            if log_cb:
                log_cb(f"Scanning: {root_abs}")
            
            for dirpath, dirnames, filenames in os.walk(root_abs):
                for filename in filenames:
                    file_path = os.path.join(dirpath, filename)
                    
                    try:
                        stat = os.stat(file_path)
                        rel_path = os.path.relpath(file_path, self.base_path)
                        
                        # Určení root_rel_path
                        root_rel_path = root_rel
                        if not rel_path.startswith(root_rel):
                            # Najít nejbližší root
                            for r in roots:
                                if rel_path.startswith(r):
                                    root_rel_path = r
                                    break
                        
                        entry = FileEntry(
                            full_rel_path=rel_path.replace("\\", "/"),  # Normalizace pro cross-platform
                            size=stat.st_size,
                            mtime_epoch=stat.st_mtime,
                            root_rel_path=root_rel_path.replace("\\", "/")
                        )
                        
                        count += 1
                        if progress_cb:
                            progress_cb(count, rel_path)
                        
                        yield entry
                    except (OSError, PermissionError) as e:
                        if log_cb:
                            log_cb(f"Error accessing {file_path}: {e}")
                        continue

