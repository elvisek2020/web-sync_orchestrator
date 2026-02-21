"""
SSH/SFTP scan adapter
"""
import logging
import paramiko
from typing import Iterator, List, Optional, Callable
from backend.adapters.base import ScanAdapter, FileEntry

logger = logging.getLogger(__name__)

class SshScanAdapter(ScanAdapter):
    """Scan adapter pro SSH/SFTP přístup"""
    
    def __init__(self, host: str, port: int = 22, username: str = "", password: str = "", key_file: Optional[str] = None, base_path: str = "/"):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.key_file = key_file
        self.base_path = base_path.rstrip("/")
        self.client: Optional[paramiko.SSHClient] = None
        self.sftp: Optional[paramiko.SFTPClient] = None
    
    def _connect(self):
        """Připojí se k SSH serveru"""
        if self.client:
            return
        
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        try:
            if self.key_file:
                self.client.connect(
                    self.host,
                    port=self.port,
                    username=self.username,
                    key_filename=self.key_file
                )
            else:
                self.client.connect(
                    self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password
                )
            
            self.sftp = self.client.open_sftp()
        except Exception as e:
            self.client = None
            raise Exception(f"Failed to connect to SSH: {e}")
    
    def _disconnect(self):
        """Odpojí se od SSH serveru"""
        if self.sftp:
            self.sftp.close()
            self.sftp = None
        if self.client:
            self.client.close()
            self.client = None
    
    def _compute_rel_path(self, remote_item_path: str) -> str:
        """Compute full_rel_path from an absolute remote path, relative to base_path.
        
        Produces the same format as local adapter's os.path.relpath() - e.g. "root/sub/file.mkv"
        """
        if not self.base_path or self.base_path == "/":
            return remote_item_path.lstrip("/")
        
        bp = self.base_path.rstrip("/")
        # Ensure proper prefix match (base_path followed by "/" separator)
        if remote_item_path == bp:
            return ""
        if remote_item_path.startswith(bp + "/"):
            return remote_item_path[len(bp) + 1:]
        # base_path not in path - use path without leading slash
        return remote_item_path.lstrip("/")

    def _walk_sftp(self, remote_path: str, root_rel: str, log_cb: Optional[Callable[[str], None]] = None, depth: int = 0):
        """Rekurzivní procházení SFTP adresáře"""
        try:
            logger.debug(f"_walk_sftp: {remote_path} (depth: {depth})")
            if log_cb and depth == 0:
                log_cb(f"Walking directory: {remote_path}")
            
            try:
                items = self.sftp.listdir_attr(remote_path)
                logger.debug(f"listdir_attr returned {len(items)} items")
            except Exception as e:
                logger.debug(f"Error listing directory {remote_path}: {e}")
                if log_cb:
                    log_cb(f"Error listing directory {remote_path}: {e}")
                return
            
            if log_cb:
                log_cb(f"Found {len(items)} items in {remote_path}")
            
            if len(items) == 0:
                logger.debug(f"Directory {remote_path} is empty")
                if log_cb:
                    log_cb(f"Directory {remote_path} is empty")
                return
            
            files_count = 0
            dirs_count = 0
            
            for item in items:
                remote_item_path = f"{remote_path}/{item.filename}" if remote_path != "/" else f"/{item.filename}"
                
                is_dir = (item.st_mode & 0o170000) == 0o040000
                
                if is_dir:
                    dirs_count += 1
                    logger.debug(f"Directory found: {remote_item_path}")
                    if log_cb and depth < 2:
                        log_cb(f"Entering directory: {remote_item_path}")
                    yield from self._walk_sftp(remote_item_path, root_rel, log_cb, depth + 1)
                else:
                    files_count += 1
                    rel_path = self._compute_rel_path(remote_item_path)
                    
                    entry = FileEntry(
                        full_rel_path=rel_path,
                        size=item.st_size,
                        mtime_epoch=float(item.st_mtime),
                        root_rel_path=root_rel.strip("/") if root_rel else ""
                    )
                    yield entry
            
            if log_cb and depth == 0:
                log_cb(f"Directory {remote_path}: {files_count} files, {dirs_count} subdirectories")
                
        except FileNotFoundError as e:
            if log_cb:
                log_cb(f"Warning: Path not found: {remote_path} - {e}")
            # Nevyhazovat výjimku, jen logovat a pokračovat
        except PermissionError as e:
            if log_cb:
                log_cb(f"Warning: Permission denied for {remote_path} - {e}")
            # Nevyhazovat výjimku, jen logovat a pokračovat
        except Exception as e:
            if log_cb:
                log_cb(f"Error walking {remote_path}: {e}")
            # Pro ostatní chyby vyhodit výjimku
            raise Exception(f"Error walking {remote_path}: {e}")
    
    def list_files(
        self,
        roots: List[str],
        progress_cb: Optional[Callable[[int, str], None]] = None,
        log_cb: Optional[Callable[[str], None]] = None
    ) -> Iterator[FileEntry]:
        """Listuje soubory přes SFTP"""
        logger.debug(f"Starting list_files with roots: {roots}, base_path: {self.base_path}")
        self._connect()
        count = 0
        
        try:
            for root_rel in roots:
                logger.debug(f"Processing root: {root_rel}")
                root_rel_clean = root_rel.strip("/")
                
                # Kombinace base_path a root_rel
                # Pokud base_path je prázdný nebo "/", použij root_rel jako absolutní cestu
                if not self.base_path or self.base_path == "/":
                    # Pokud root_rel je absolutní, použij ho přímo
                    if root_rel.startswith("/"):
                        remote_path = root_rel
                    else:
                        # Relativní cesta - přidej úvodní lomítko
                        remote_path = f"/{root_rel_clean}"
                else:
                    # Base_path je nastavený - kombinuj s root_rel
                    if root_rel.startswith("/"):
                        # Pokud root_rel je absolutní, ignoruj base_path a použij root_rel
                        # (to může být problém, ale uživatel zadal absolutní cestu)
                        remote_path = root_rel
                    else:
                        # Relativní cesta - kombinuj s base_path
                        remote_path = f"{self.base_path.rstrip('/')}/{root_rel_clean}"
                
                # Normalizace - odstranit dvojitá lomítka
                remote_path = remote_path.replace("//", "/")
                if remote_path == "":
                    remote_path = "/"
                
                logger.debug(f"Final remote_path: {remote_path}")
                
                if log_cb:
                    log_cb(f"Scanning via SSH: {remote_path}")
                
                # Ověření existence cesty před scanováním
                # Nejdřív zkusit listovat root adresář, abychom viděli, co tam je
                try:
                    if log_cb:
                        log_cb(f"Testing connection - listing root directory...")
                    root_items = self.sftp.listdir("/")
                    logger.debug(f"Root directory (/) contains: {root_items[:10]}")
                    if log_cb:
                        log_cb(f"Root directory (/) contains: {', '.join(root_items[:10])}...")
                except Exception as e:
                    logger.debug(f"Cannot list root directory: {e}")
                    if log_cb:
                        log_cb(f"Warning: Cannot list root directory: {e}")
                
                try:
                    volume1_items = self.sftp.listdir("/volume1")
                    logger.debug(f"/volume1 directory contains: {volume1_items[:10]}")
                    if log_cb:
                        log_cb(f"/volume1 directory contains: {', '.join(volume1_items[:10])}...")
                except Exception as e:
                    logger.debug(f"Cannot list /volume1: {e}")
                    if log_cb:
                        log_cb(f"Cannot list /volume1: {e}")
                
                path_parts = remote_path.strip("/").split("/")
                test_path = ""
                found_path = None
                
                alternative_paths = [
                    remote_path,
                    remote_path.replace("/volume1/", "/"),
                    f"/volume1{remote_path}" if not remote_path.startswith("/volume1") else remote_path,
                ]
                alternative_paths = list(dict.fromkeys(alternative_paths))
                
                for alt_path in alternative_paths:
                    try:
                        stat_info = self.sftp.stat(alt_path)
                        is_dir = (stat_info.st_mode & 0o170000) == 0o040000
                        logger.debug(f"Alternative path exists: {alt_path}, is_dir: {is_dir}")
                        if is_dir:
                            found_path = alt_path
                            remote_path = alt_path
                            if log_cb:
                                log_cb(f"Found directory at: {alt_path}")
                            try:
                                items = self.sftp.listdir(alt_path)
                                logger.debug(f"Directory {alt_path} contains: {items[:10]}")
                                if log_cb:
                                    log_cb(f"Directory {alt_path} contains: {', '.join(items[:10])}...")
                            except:
                                pass
                            break
                    except FileNotFoundError:
                        logger.debug(f"Alternative path does not exist: {alt_path}")
                    except Exception as e:
                        logger.debug(f"Error checking alternative path {alt_path}: {e}")
                
                if not found_path:
                    for part in path_parts:
                        if not part:
                            continue
                        test_path = test_path + "/" + part if test_path else "/" + part
                        try:
                            stat_info = self.sftp.stat(test_path)
                            is_dir = (stat_info.st_mode & 0o170000) == 0o040000
                            logger.debug(f"Path exists: {test_path}, is_dir: {is_dir}")
                            if is_dir:
                                found_path = test_path
                                if log_cb:
                                    log_cb(f"Found directory: {test_path}")
                                try:
                                    items = self.sftp.listdir(test_path)
                                    logger.debug(f"Directory {test_path} contains: {items[:10]}")
                                    if log_cb:
                                        log_cb(f"Directory {test_path} contains: {', '.join(items[:10])}...")
                                except:
                                    pass
                        except FileNotFoundError:
                            logger.debug(f"Path does not exist: {test_path}")
                            if log_cb:
                                log_cb(f"Path does not exist: {test_path}")
                            break
                        except Exception as e:
                            logger.debug(f"Error checking path {test_path}: {e}")
                            if log_cb:
                                log_cb(f"Error checking path {test_path}: {e}")
                            break
                
                if found_path and found_path != remote_path:
                    try:
                        items = self.sftp.listdir(found_path)
                        logger.debug(f"Last existing path: {found_path}, contains: {items}")
                        if log_cb:
                            log_cb(f"Last existing path: {found_path}, contains: {', '.join(items[:20])}")
                    except:
                        pass
                
                try:
                    stat_info = self.sftp.stat(remote_path)
                    logger.debug(f"Final path exists: {remote_path}, mode: {oct(stat_info.st_mode)}")
                    is_dir = (stat_info.st_mode & 0o170000) == 0o040000
                    logger.debug(f"Is directory: {is_dir}")
                    if not is_dir:
                        if log_cb:
                            log_cb(f"Error: Path is not a directory: {remote_path}")
                        raise Exception(f"Path is not a directory: {remote_path}")
                except FileNotFoundError as e:
                    logger.debug(f"Final path not found: {remote_path} - {e}")
                    parent_items = []
                    parent_path = "/".join(remote_path.rstrip("/").split("/")[:-1]) or "/"
                    try:
                        if log_cb:
                            log_cb(f"Path not found. Trying to list parent directory: {parent_path}")
                        parent_items = self.sftp.listdir(parent_path)
                        logger.debug(f"Parent directory ({parent_path}) contains: {parent_items}")
                        if log_cb:
                            log_cb(f"Parent directory ({parent_path}) contains: {', '.join(parent_items[:20])}")
                    except Exception as pe:
                        logger.debug(f"Cannot list parent {parent_path}: {pe}")
                        if log_cb:
                            log_cb(f"Cannot list parent directory {parent_path}: {pe}")
                        try:
                            root_items = self.sftp.listdir("/")
                            logger.debug(f"Root directory contains: {root_items}")
                            if log_cb:
                                log_cb(f"Root directory contains: {', '.join(root_items[:20])}")
                            parent_items = root_items
                            parent_path = "/"
                        except:
                            pass
                    
                    path_name = remote_path.rstrip("/").split("/")[-1]
                    suggestions = []
                    if parent_items:
                        for item in parent_items:
                            if path_name.lower() in item.lower() or item.lower() in path_name.lower():
                                suggested_path = f"{parent_path.rstrip('/')}/{item}" if parent_path != "/" else f"/{item}"
                                suggestions.append(suggested_path)
                    
                    parent_info = f"{', '.join(parent_items[:20])}" if parent_items else "cannot list"
                    suggestion_text = f" Možné správné cesty: {', '.join(suggestions[:5])}" if suggestions else ""
                    error_msg = f"Path does not exist on remote server: {remote_path}. Parent directory ({parent_path}) contains: {parent_info}.{suggestion_text}"
                    logger.warning(error_msg)
                    if log_cb:
                        log_cb(f"Error: {error_msg}")
                    raise Exception(error_msg)
                except Exception as e:
                    logger.debug(f"Error accessing final path: {remote_path} - {e}")
                    if log_cb:
                        log_cb(f"Error: Cannot access path {remote_path}: {e}")
                    raise
                
                logger.debug(f"Starting _walk_sftp for: {remote_path}")
                entry_count = 0
                for entry in self._walk_sftp(remote_path, root_rel_clean, log_cb):
                    entry_count += 1
                    count += 1
                    if progress_cb:
                        progress_cb(count, entry.full_rel_path)
                    yield entry
                
                logger.debug(f"_walk_sftp completed: {entry_count} entries yielded")
                
                if log_cb:
                    log_cb(f"Completed scanning {remote_path}: {count} files found")
        finally:
            self._disconnect()

