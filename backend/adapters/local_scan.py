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
        
        # Normalizace base_path pro bezpečnostní kontroly
        base_path_abs = os.path.abspath(os.path.normpath(self.base_path))
        
        for root_rel in roots:
            # Normalizace root_rel - odstranit úvodní lomítka
            root_rel_clean = root_rel.strip("/")
            
            # Vytvoření absolutní cesty k root složce
            if root_rel_clean:
                root_abs = os.path.join(self.base_path, root_rel_clean)
            else:
                # Pokud root_rel je prázdný nebo "/", použij base_path
                root_abs = self.base_path
            
            # Normalizace absolutní cesty
            root_abs = os.path.abspath(os.path.normpath(root_abs))
            
            # Bezpečnostní kontrola - root_abs musí být pod base_path
            try:
                common_path = os.path.commonpath([base_path_abs, root_abs])
                if common_path != base_path_abs:
                    if log_cb:
                        log_cb(f"Warning: Root path is outside base_path: {root_abs} (base: {base_path_abs})")
                    continue
            except ValueError:
                # Pokud commonpath selže (různé disky), cesta je mimo base_path
                if log_cb:
                    log_cb(f"Warning: Root path is outside base_path: {root_abs} (base: {base_path_abs})")
                continue
            
            if not os.path.exists(root_abs):
                if log_cb:
                    log_cb(f"Warning: Root path does not exist: {root_abs}")
                continue
            
            if not os.path.isdir(root_abs):
                if log_cb:
                    log_cb(f"Warning: Root path is not a directory: {root_abs}")
                continue
            
            if log_cb:
                log_cb(f"Scanning: {root_abs} (base: {base_path_abs})")
            
            for dirpath, dirnames, filenames in os.walk(root_abs):
                # Normalizace dirpath pro bezpečnostní kontrolu
                dirpath_abs = os.path.abspath(os.path.normpath(dirpath))
                
                # Bezpečnostní kontrola - dirpath musí být pod base_path
                try:
                    common_path = os.path.commonpath([base_path_abs, dirpath_abs])
                    if common_path != base_path_abs:
                        # Pokud jsme mimo base_path, přeskočit tento adresář
                        if log_cb:
                            log_cb(f"Warning: Directory outside base_path, skipping: {dirpath_abs}")
                        dirnames[:] = []  # Zastavit procházení do podadresářů
                        continue
                except ValueError:
                    # Pokud commonpath selže, přeskočit
                    dirnames[:] = []
                    continue
                
                for filename in filenames:
                    file_path = os.path.join(dirpath, filename)
                    file_path_abs = os.path.abspath(os.path.normpath(file_path))
                    
                    # Bezpečnostní kontrola - file_path musí být pod base_path
                    try:
                        common_path = os.path.commonpath([base_path_abs, file_path_abs])
                        if common_path != base_path_abs:
                            # Soubor je mimo base_path, přeskočit
                            continue
                    except ValueError:
                        # Pokud commonpath selže, přeskočit
                        continue
                    
                    try:
                        stat = os.stat(file_path)
                        
                        # Vytvoření relativní cesty k base_path
                        rel_path = os.path.relpath(file_path_abs, base_path_abs)
                        rel_path = rel_path.replace("\\", "/")  # Normalizace pro cross-platform
                        
                        # Pokud rel_path začíná "..", znamená to, že jsme mimo base_path
                        if rel_path.startswith("../"):
                            if log_cb:
                                log_cb(f"Warning: File path outside base_path, skipping: {file_path_abs}")
                            continue
                        
                        # Určení root_rel_path
                        root_rel_path = root_rel_clean if root_rel_clean else "/"
                        
                        # Pokud rel_path nezačíná root_rel, zkusit najít správný root
                        if root_rel_clean and not rel_path.startswith(root_rel_clean + "/") and rel_path != root_rel_clean:
                            # Zkusit najít nejbližší root
                            for r in roots:
                                r_clean = r.strip("/")
                                if r_clean and (rel_path.startswith(r_clean + "/") or rel_path == r_clean):
                                    root_rel_path = r_clean
                                    break
                        
                        entry = FileEntry(
                            full_rel_path=rel_path,
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

