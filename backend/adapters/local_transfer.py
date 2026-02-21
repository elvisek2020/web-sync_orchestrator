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
            
            # Build lookup dict for O(1) file matching
            files_by_path = {f.full_rel_path: f for f in files}
            
            copied = 0
            copied_files = set()
            rsync_info_prefixes = ("building", "sending", "total size is", "speedup is", "sent ", "received ")
            
            for line in process.stdout:
                if log_cb:
                    log_cb(line.strip())
                line_stripped = line.strip()
                
                if not line_stripped or line_stripped.startswith(rsync_info_prefixes) or line_stripped.endswith("/"):
                    continue
                
                matched_file = None
                file_size = 0
                
                if line_stripped in files_by_path:
                    matched_file = line_stripped
                    file_size = files_by_path[line_stripped].size
                
                if matched_file and matched_file not in copied_files:
                    copied_files.add(matched_file)
                    copied += 1
                    if progress_cb:
                        progress_cb(copied, matched_file, file_size, success=True, error=None)
            
            returncode = process.wait()
            
            if returncode != 0:
                error_output = process.stderr.read()
                # Pokud některé soubory selhaly, označit je jako failed
                if progress_cb and copied_files:
                    for failed_file in copied_files:
                        progress_cb(copied, failed_file, 0, success=False, error=f"Rsync failed with code {returncode}")
                raise Exception(f"Rsync failed with code {returncode}: {error_output}")
            
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

