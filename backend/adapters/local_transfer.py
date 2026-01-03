"""
Local filesystem transfer adapter (rsync)
"""
import subprocess
import os
from typing import List, Optional, Callable
from backend.adapters.base import TransferAdapter, FileEntry

class LocalRsyncTransferAdapter(TransferAdapter):
    """Transfer adapter pro lokální rsync"""
    
    def send_batch(
        self,
        files: List[FileEntry],
        source_base: str,
        target_base: str,
        dry_run: bool = False,
        progress_cb: Optional[Callable[[int, str], None]] = None,
        log_cb: Optional[Callable[[str], None]] = None
    ) -> dict:
        """Kopíruje soubory pomocí rsync"""
        
        if log_cb:
            log_cb(f"Starting rsync transfer: {len(files)} files")
            if dry_run:
                log_cb("DRY RUN mode - no files will be copied")
        
        # Vytvoření seznamu souborů pro --files-from
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            for file_entry in files:
                # Rsync očekává relativní cesty od source_base
                f.write(f"{file_entry.full_rel_path}\n")
            files_list_path = f.name
        
        try:
            # Rsync příkaz
            cmd = [
                "rsync",
                "-av",  # archive mode, verbose
                "--partial",  # Podpora pro pokračování přerušených přenosů
                "--files-from", files_list_path,
                source_base + "/",
                target_base + "/"
            ]
            
            if dry_run:
                cmd.append("--dry-run")
            
            if log_cb:
                log_cb(f"Running: {' '.join(cmd)}")
            
            # Spuštění rsync
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            
            # Čtení výstupu řádek po řádku
            copied = 0
            current_file = ""
            for line in process.stdout:
                if log_cb:
                    log_cb(line.strip())
                # Rsync výstup: "filename" nebo "filename\n"
                line_stripped = line.strip()
                if line_stripped and not line_stripped.startswith("building") and not line_stripped.startswith("sending"):
                    # Najít odpovídající soubor pro získání velikosti
                    current_file = line_stripped
                    file_size = 0
                    for file_entry in files:
                        if file_entry.full_rel_path.endswith(current_file) or current_file.endswith(file_entry.full_rel_path):
                            file_size = file_entry.size
                            break
                    copied += 1
                    if progress_cb:
                        progress_cb(copied, current_file, file_size)
            
            process.wait()
            
            if process.returncode != 0:
                error_output = process.stderr.read()
                raise Exception(f"Rsync failed with code {process.returncode}: {error_output}")
            
            return {
                "success": True,
                "files_copied": copied,
                "dry_run": dry_run
            }
            
        finally:
            # Smazání dočasného souboru
            try:
                os.unlink(files_list_path)
            except:
                pass

