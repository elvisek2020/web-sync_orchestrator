"""
SSH/SFTP scan adapter – robust version with retry, reconnection and encoding fixes.
"""
import logging
import time
import stat as stat_module
import unicodedata
import paramiko
from typing import Iterator, List, Optional, Callable

from backend.adapters.base import ScanAdapter, FileEntry

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY = 2
BATCH_RECONNECT_THRESHOLD = 3


def _try_fix_encoding(name: str) -> str:
    """Attempt to repair double-encoded UTF-8 filenames (mojibake).

    Some NAS systems store UTF-8 bytes but the SFTP layer re-interprets them
    through an 8-bit codepage (cp1252 / latin-1).  We try the reverse
    transformation: encode back to the suspected codepage → decode as UTF-8.
    If neither candidate works we return the original string.
    """
    if name.isascii():
        return name
    for codec in ("cp1252", "latin-1", "cp1250", "iso-8859-2"):
        try:
            candidate = name.encode(codec).decode("utf-8")
            if candidate != name:
                return candidate
        except (UnicodeDecodeError, UnicodeEncodeError):
            continue
    return name


class SshScanAdapter(ScanAdapter):
    """Scan adapter pro SSH/SFTP přístup – s retry, reconnect a encoding fixem."""

    def __init__(self, host: str, port: int = 22, username: str = "",
                 password: str = "", key_file: Optional[str] = None,
                 base_path: str = "/"):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.key_file = key_file
        self.base_path = base_path.rstrip("/")
        self.client: Optional[paramiko.SSHClient] = None
        self.sftp: Optional[paramiko.SFTPClient] = None
        # scan-level statistics
        self.stats = {
            "dirs_visited": 0,
            "dirs_skipped": 0,
            "files_found": 0,
            "errors": [],          # list of (path, error_str)
            "encoding_fixes": 0,
        }

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def _connect(self):
        if self.client and self.sftp:
            try:
                self.sftp.stat(".")
                return
            except Exception:
                self._disconnect()

        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            kw = dict(hostname=self.host, port=self.port, username=self.username)
            if self.key_file:
                kw["key_filename"] = self.key_file
            else:
                kw["password"] = self.password

            self.client.connect(**kw, timeout=30, banner_timeout=30)
            transport = self.client.get_transport()
            if transport:
                transport.set_keepalive(15)
            self.sftp = self.client.open_sftp()
            self.sftp.get_channel().settimeout(60)
        except Exception as e:
            self.client = None
            raise Exception(f"Failed to connect to SSH {self.host}:{self.port}: {e}")

    def _disconnect(self):
        if self.sftp:
            try:
                self.sftp.close()
            except Exception:
                pass
            self.sftp = None
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
            self.client = None

    def _ensure_connection(self):
        """Reconnect if the connection was dropped."""
        try:
            if self.sftp:
                self.sftp.stat(".")
                return
        except Exception:
            pass
        self._disconnect()
        self._connect()

    # ------------------------------------------------------------------
    # SFTP helpers with retry
    # ------------------------------------------------------------------

    def _listdir_attr_safe(self, path: str) -> Optional[list]:
        """listdir_attr with retry & reconnect on failure."""
        last_err = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                self._ensure_connection()
                items = self.sftp.listdir_attr(path)
                return items
            except Exception as e:
                last_err = e
                logger.warning(f"listdir_attr({path}) attempt {attempt}/{MAX_RETRIES} failed: {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY * attempt)
                    self._disconnect()
        return None

    # ------------------------------------------------------------------
    # Path computation
    # ------------------------------------------------------------------

    def _compute_rel_path(self, remote_item_path: str) -> str:
        """Compute full_rel_path relative to base_path."""
        if not self.base_path or self.base_path == "/":
            return remote_item_path.lstrip("/")

        bp = self.base_path.rstrip("/")
        if remote_item_path == bp:
            return ""
        if remote_item_path.startswith(bp + "/"):
            return remote_item_path[len(bp) + 1:]
        return remote_item_path.lstrip("/")

    def _fix_filename(self, name: str) -> str:
        """Apply encoding fix + NFC normalization to a single filename."""
        fixed = _try_fix_encoding(name)
        if fixed != name:
            self.stats["encoding_fixes"] += 1
        return unicodedata.normalize("NFC", fixed)

    # ------------------------------------------------------------------
    # Recursive walker
    # ------------------------------------------------------------------

    def _walk_sftp(self, remote_path: str, root_rel: str,
                   log_cb: Optional[Callable[[str], None]] = None,
                   depth: int = 0) -> Iterator[FileEntry]:
        """Recursively walk a remote directory, yielding FileEntry objects."""
        items = self._listdir_attr_safe(remote_path)
        if items is None:
            err_msg = f"Failed to list directory after {MAX_RETRIES} retries: {remote_path}"
            logger.error(err_msg)
            self.stats["dirs_skipped"] += 1
            self.stats["errors"].append((remote_path, err_msg))
            if log_cb:
                log_cb(f"ERROR: {err_msg}")
            return

        self.stats["dirs_visited"] += 1
        if log_cb and depth < 2:
            log_cb(f"Scanning: {remote_path} ({len(items)} items)")

        files_count = 0
        dirs_count = 0

        for item in items:
            try:
                filename = self._fix_filename(item.filename)
                child_path = f"{remote_path}/{filename}" if remote_path != "/" else f"/{filename}"

                is_dir = stat_module.S_ISDIR(item.st_mode)

                if is_dir:
                    dirs_count += 1
                    yield from self._walk_sftp(child_path, root_rel, log_cb, depth + 1)
                else:
                    files_count += 1
                    self.stats["files_found"] += 1
                    rel_path = self._compute_rel_path(child_path)

                    entry = FileEntry(
                        full_rel_path=rel_path,
                        size=item.st_size,
                        mtime_epoch=float(item.st_mtime),
                        root_rel_path=root_rel.strip("/") if root_rel else ""
                    )
                    yield entry

            except Exception as e:
                child_name = getattr(item, "filename", "?")
                err_msg = f"Error processing {remote_path}/{child_name}: {e}"
                logger.warning(err_msg)
                self.stats["errors"].append((f"{remote_path}/{child_name}", str(e)))
                if log_cb:
                    log_cb(f"WARNING: {err_msg}")
                continue

        if log_cb and depth == 0:
            log_cb(f"Directory {remote_path}: {files_count} files, {dirs_count} subdirectories")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_files(
        self,
        roots: List[str],
        progress_cb: Optional[Callable[[int, str], None]] = None,
        log_cb: Optional[Callable[[str], None]] = None,
    ) -> Iterator[FileEntry]:
        """List files via SFTP with full error handling and retry logic."""
        self._connect()
        count = 0

        try:
            for root_rel in roots:
                root_rel_clean = root_rel.strip("/")

                if not self.base_path or self.base_path == "/":
                    remote_path = f"/{root_rel_clean}" if not root_rel.startswith("/") else root_rel
                else:
                    if root_rel.startswith("/"):
                        remote_path = root_rel
                    else:
                        remote_path = f"{self.base_path.rstrip('/')}/{root_rel_clean}"

                remote_path = remote_path.replace("//", "/") or "/"

                if log_cb:
                    log_cb(f"Scanning via SSH: {remote_path}")

                # Verify path exists
                resolved_path = self._resolve_remote_path(remote_path, log_cb)
                if resolved_path is None:
                    err_msg = f"Remote path not found: {remote_path}"
                    self.stats["errors"].append((remote_path, err_msg))
                    if log_cb:
                        log_cb(f"ERROR: {err_msg}")
                    continue
                remote_path = resolved_path

                if log_cb:
                    log_cb(f"Resolved remote path: {remote_path}")

                entry_count = 0
                for entry in self._walk_sftp(remote_path, root_rel_clean, log_cb):
                    entry_count += 1
                    count += 1
                    if progress_cb:
                        progress_cb(count, entry.full_rel_path)
                    yield entry

                if log_cb:
                    log_cb(f"Completed {remote_path}: {entry_count} files")

            # Summary
            summary = (
                f"Scan summary: dirs_visited={self.stats['dirs_visited']}, "
                f"dirs_skipped={self.stats['dirs_skipped']}, "
                f"files_found={self.stats['files_found']}, "
                f"encoding_fixes={self.stats['encoding_fixes']}, "
                f"errors={len(self.stats['errors'])}"
            )
            logger.info(summary)
            if log_cb:
                log_cb(summary)
                if self.stats["errors"]:
                    log_cb(f"--- Error details ({len(self.stats['errors'])}) ---")
                    for path, err in self.stats["errors"]:
                        log_cb(f"  {path}: {err}")

        finally:
            self._disconnect()

    # ------------------------------------------------------------------
    # Path resolution
    # ------------------------------------------------------------------

    def _resolve_remote_path(self, remote_path: str,
                             log_cb: Optional[Callable[[str], None]] = None) -> Optional[str]:
        """Verify that remote_path exists. Try alternatives if not found."""
        candidates = [remote_path]
        if "/volume1" not in remote_path:
            candidates.append(f"/volume1{remote_path}")
        if remote_path.startswith("/volume1/"):
            candidates.append(remote_path.replace("/volume1/", "/", 1))

        for candidate in candidates:
            try:
                self._ensure_connection()
                info = self.sftp.stat(candidate)
                if stat_module.S_ISDIR(info.st_mode):
                    return candidate
            except FileNotFoundError:
                continue
            except Exception as e:
                logger.debug(f"Error checking path {candidate}: {e}")
                continue

        # Diagnostics: list parent to help debug
        parent = "/".join(remote_path.rstrip("/").split("/")[:-1]) or "/"
        try:
            self._ensure_connection()
            parent_items = self.sftp.listdir(parent)
            if log_cb:
                log_cb(f"Path not found: {remote_path}. Parent ({parent}) contains: {', '.join(parent_items[:30])}")
        except Exception:
            if log_cb:
                log_cb(f"Path not found: {remote_path}. Cannot list parent ({parent}).")

        return None
