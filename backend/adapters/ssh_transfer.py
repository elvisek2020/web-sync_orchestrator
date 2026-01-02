"""
SSH rsync transfer adapter
"""
import subprocess
import os
from typing import List, Optional, Callable
from backend.adapters.base import TransferAdapter, FileEntry

class SshRsyncTransferAdapter(TransferAdapter):
    """Transfer adapter pro SSH rsync"""
    
    def __init__(self, host: str, port: int = 22, username: str = "", password: str = "", key_file: Optional[str] = None):
        self.host = host
        self.port = port
        self.username = username
        self.key_file = key_file
        self.password = password
    
    def send_batch(
        self,
        files: List[FileEntry],
        source_base: str,
        target_base: str,
        dry_run: bool = False,
        progress_cb: Optional[Callable[[int, str], None]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
        source_is_remote: bool = False
    ) -> dict:
        """
        Kopíruje soubory pomocí rsync přes SSH
        
        Args:
            source_is_remote: Pokud True, source je na vzdáleném serveru, target je lokální
                            Pokud False, source je lokální, target je na vzdáleném serveru
        """
        
        if log_cb:
            direction = "remote→local" if source_is_remote else "local→remote"
            log_cb(f"Starting SSH rsync transfer ({direction}): {len(files)} files")
            if dry_run:
                log_cb("DRY RUN mode - no files will be copied")
        
        # Vytvoření seznamu souborů pro --files-from
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt') as f:
            for file_entry in files:
                f.write(f"{file_entry.full_rel_path}\n")
            files_list_path = f.name
        
        try:
            # Sestavení SSH příkazu
            ssh_cmd = f"ssh -p {self.port}"
            if self.key_file:
                ssh_cmd += f" -i {self.key_file}"
            ssh_cmd += f" {self.username}@{self.host}"
            
            if source_is_remote:
                # Kopírování z VZDÁLENÉHO na LOKÁLNÍ
                remote_source = f"{self.username}@{self.host}:{source_base}"
                cmd = [
                    "rsync",
                    "-av",
                    "--partial",
                    "-e", ssh_cmd,
                    "--files-from", files_list_path,
                    remote_source + "/",
                    target_base + "/"
                ]
            else:
                # Kopírování z LOKÁLNÍHO na VZDÁLENÝ (původní chování)
                remote_target = f"{self.username}@{self.host}:{target_base}"
                cmd = [
                    "rsync",
                    "-av",
                    "--partial",
                    "-e", ssh_cmd,
                    "--files-from", files_list_path,
                    source_base + "/",
                    remote_target + "/"
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
            
            # Čtení výstupu
            copied = 0
            for line in process.stdout:
                if log_cb:
                    log_cb(line.strip())
                if not line.startswith("building") and not line.startswith("sending"):
                    copied += 1
                    if progress_cb:
                        progress_cb(copied, "")
            
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
            try:
                os.unlink(files_list_path)
            except:
                pass

