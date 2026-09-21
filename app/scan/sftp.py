"""Sken vzdálené složky přes SFTP (NAS2).

Připojení, timeouty a opakování převzaty ze staré verze (backend/adapters/ssh_scan.py).
Rozdíl: složku, kterou se nepodaří vypsat ani po opakování, sken NEpřeskočí —
skončí chybou, aby z ní nevznikly falešné „přebývající“ soubory.
"""
from __future__ import annotations

import logging
import posixpath
import stat
import time

import paramiko

from app.core.excludes import Excluder
from app.core.keys import FileRec, key_from_remote

from .common import Progress, ScanCancelled, ScanError, cz_items

logger = logging.getLogger("sync.sftp")

MAX_RETRIES = 3
RETRY_DELAY = 2


class SftpSession:
    def __init__(self, host: str, port: int, username: str, password: str):
        self.host, self.port, self.username, self.password = host, port, username, password
        self.client: paramiko.SSHClient | None = None
        self.sftp: paramiko.SFTPClient | None = None

    def connect(self) -> None:
        self.close()
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                hostname=self.host, port=self.port, username=self.username, password=self.password,
                timeout=30, banner_timeout=30, auth_timeout=30,
                allow_agent=False, look_for_keys=False,
            )
        except paramiko.AuthenticationException as e:
            raise ScanError(f"Přihlášení k {self.host}:{self.port} selhalo (jméno/heslo): {e}") from e
        except Exception as e:
            raise ScanError(f"Nelze se připojit k {self.host}:{self.port}: {e}") from e
        transport = client.get_transport()
        if transport:
            transport.set_keepalive(15)
        self.client = client
        self.sftp = client.open_sftp()
        self.sftp.get_channel().settimeout(60)

    def close(self) -> None:
        for obj in (self.sftp, self.client):
            try:
                if obj is not None:
                    obj.close()
            except Exception:
                pass
        self.sftp = self.client = None

    def _retry(self, what: str, fn, progress: Progress | None = None):
        last: Exception | None = None
        for attempt in range(1, MAX_RETRIES + 1):
            if progress:
                progress.check_cancel()
            try:
                if self.sftp is None:
                    self.connect()
                return fn(self.sftp)
            except (FileNotFoundError, PermissionError, ScanCancelled):
                raise
            except ScanError:
                raise
            except Exception as e:  # výpadek spojení, timeout…
                last = e
                logger.warning("%s: pokus %d/%d selhal: %s", what, attempt, MAX_RETRIES, e)
                if progress:
                    progress.log(f"Opakuji ({attempt}/{MAX_RETRIES}) {what}: {e}")
                self.close()
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY * attempt)
        raise ScanError(f"{what} selhalo ani po {MAX_RETRIES} pokusech: {last}")

    def stat(self, path: str, progress: Progress | None = None):
        return self._retry(f"stat {path}", lambda s: s.stat(path), progress)

    def listdir_attr(self, path: str, progress: Progress | None = None):
        return self._retry(f"výpis {path}", lambda s: s.listdir_attr(path), progress)

    def describe_missing(self, path: str) -> str:
        parent = posixpath.dirname(path.rstrip("/")) or "/"
        try:
            names = sorted(a.filename for a in self.listdir_attr(parent))
            return f"Složka {path} neexistuje. V {parent} je: {', '.join(names[:30])}"
        except Exception:
            return f"Složka {path} neexistuje (ani {parent} nejde vypsat)."


def scan_sftp(host: dict, root: str, excluder: Excluder, progress: Progress, *, allow_empty: bool) -> list[FileRec]:
    root = "/" + root.strip("/") if root.strip("/") else "/"
    session = SftpSession(host["host"], int(host["port"]), host["username"], host["password"])
    progress.log(f"Připojuji se k {host['username']}@{host['host']}:{host['port']}")
    session.connect()
    try:
        try:
            st = session.stat(root, progress)
        except FileNotFoundError:
            raise ScanError(session.describe_missing(root))
        if not stat.S_ISDIR(st.st_mode):
            raise ScanError(f"Cesta není složka: {root}")

        progress.log(f"Skenuji přes SFTP: {root}")
        records: list[FileRec] = []
        stack: list[str] = [""]
        while stack:
            progress.check_cancel()
            rel_dir = stack.pop()
            abs_dir = posixpath.join(root, rel_dir) if rel_dir else root
            progress.current = rel_dir or "/"
            try:
                items = session.listdir_attr(abs_dir, progress)
            except (FileNotFoundError, PermissionError) as e:
                raise ScanError(f"Nelze přečíst složku „{rel_dir or '/'}“: {e}") from e
            progress.dirs += 1
            if rel_dir.count("/") < 1:
                progress.log(f"Složka {rel_dir or '/'} ({cz_items(len(items))})")

            for attr in items:
                name = attr.filename
                if name in (".", ".."):
                    continue
                rel = f"{rel_dir}/{name}" if rel_dir else name
                if excluder.excluded_name(key_from_remote(name)):
                    continue
                mode = attr.st_mode or 0
                if stat.S_ISLNK(mode):
                    progress.log(f"Přeskakuji symbolický odkaz: {rel}")
                elif stat.S_ISDIR(mode):
                    stack.append(rel)
                elif stat.S_ISREG(mode):
                    key = key_from_remote(rel)
                    if excluder.excluded(key):
                        continue
                    records.append(FileRec(rel.encode("utf-8"), key, int(attr.st_size or 0), float(attr.st_mtime or 0)))
                    progress.files += 1
                    progress.bytes += int(attr.st_size or 0)

        if not records and not allow_empty:
            raise ScanError(f"Ve složce {root} není žádný soubor.")
        progress.log(f"Hotovo: {len(records)} souborů, {progress.dirs} složek")
        return records
    finally:
        session.close()


def test_connection(host: dict, path: str | None = None) -> str:
    """Pro Nastavení: ověří přihlášení (a volitelně složku). Vrací popis výsledku, při chybě ScanError."""
    session = SftpSession(host["host"], int(host["port"]), host["username"], host["password"])
    session.connect()
    try:
        if not path:
            return f"Přihlášení k {host['host']}:{host['port']} je v pořádku."
        root = "/" + path.strip("/")
        try:
            st = session.stat(root)
        except FileNotFoundError:
            raise ScanError(session.describe_missing(root))
        if not stat.S_ISDIR(st.st_mode):
            raise ScanError(f"Cesta není složka: {root}")
        count = len(session.listdir_attr(root))
        return f"Složka {root} existuje ({cz_items(count)})."
    finally:
        session.close()
