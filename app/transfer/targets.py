"""Cíl přímého přenosu: vzdálený NAS přes SFTP, nebo lokální složka (testy, lokální pár).

Obě třídy mají stejné rozhraní; cesty jsou relativní k rootu cíle (bajty jako ze skenu).
"""
from __future__ import annotations

import errno
import os
import posixpath
import stat
from typing import BinaryIO, Protocol

import paramiko

from app.scan.sftp import SftpSession

# Dočasná přípona rozpracovaného souboru — na cíli nikdy nezůstane napůl nahraný soubor.
PART_SUFFIX = ".syncpart"


def as_str(path: bytes) -> str:
    """Cesta ze skenu (bajty) jako text pro souborové API."""
    return path.decode("utf-8", "surrogateescape")


def part_name(rel: str) -> str:
    head, tail = posixpath.split(rel)
    return posixpath.join(head, f".{tail}{PART_SUFFIX}")


class Target(Protocol):
    def connect(self) -> None: ...
    def close(self) -> None: ...
    def size(self, rel: str) -> int | None: ...
    def makedirs(self, rel_dir: str) -> None: ...
    def open_write(self, rel: str, offset: int) -> BinaryIO: ...
    def replace(self, src_rel: str, dst_rel: str) -> None: ...
    def set_mtime(self, rel: str, mtime: float) -> None: ...
    def remove(self, rel: str) -> None: ...
    def remove_empty_dirs(self, rel_dir: str) -> None: ...


class SftpTarget:
    def __init__(self, host: dict, root: str):
        self.session = SftpSession(host["host"], int(host["port"]), host["username"], host["password"])
        self.root = "/" + root.strip("/") if root.strip("/") else "/"

    def _abs(self, rel: str) -> str:
        return posixpath.join(self.root, rel) if rel else self.root

    @property
    def sftp(self) -> paramiko.SFTPClient:
        if self.session.sftp is None:
            self.session.connect()
        return self.session.sftp

    def connect(self) -> None:
        self.session.connect()

    def close(self) -> None:
        self.session.close()

    def size(self, rel: str) -> int | None:
        try:
            return self.sftp.stat(self._abs(rel)).st_size
        except FileNotFoundError:
            return None

    def makedirs(self, rel_dir: str) -> None:
        path = self.root
        for part in [p for p in rel_dir.split("/") if p]:
            path = posixpath.join(path, part)
            try:
                if not stat.S_ISDIR(self.sftp.stat(path).st_mode):
                    raise OSError(errno.ENOTDIR, f"{path} není složka")
            except FileNotFoundError:
                self.sftp.mkdir(path)

    def open_write(self, rel: str, offset: int):
        if offset:
            f = self.sftp.open(self._abs(rel), "r+")
            f.seek(offset)
        else:
            f = self.sftp.open(self._abs(rel), "w")
        f.set_pipelined(True)
        return f

    def replace(self, src_rel: str, dst_rel: str) -> None:
        src, dst = self._abs(src_rel), self._abs(dst_rel)
        try:
            self.sftp.posix_rename(src, dst)          # OpenSSH rozšíření: přepíše cíl atomicky
        except OSError:
            if self.size(dst_rel) is not None:
                self.sftp.remove(dst)
            self.sftp.rename(src, dst)

    def set_mtime(self, rel: str, mtime: float) -> None:
        self.sftp.utime(self._abs(rel), (mtime, mtime))

    def remove(self, rel: str) -> None:
        self.sftp.remove(self._abs(rel))

    def remove_empty_dirs(self, rel_dir: str) -> None:
        while rel_dir:
            try:
                self.sftp.rmdir(self._abs(rel_dir))   # smaže jen prázdnou složku
            except OSError:
                return
            rel_dir = posixpath.dirname(rel_dir)


class LocalTarget:
    def __init__(self, root: str):
        self.root = root

    def _abs(self, rel: str) -> str:
        return os.path.join(self.root, rel) if rel else self.root

    def connect(self) -> None:
        if not os.path.isdir(self.root):
            raise FileNotFoundError(self.root)

    def close(self) -> None:
        pass

    def size(self, rel: str) -> int | None:
        try:
            return os.stat(self._abs(rel)).st_size
        except FileNotFoundError:
            return None

    def makedirs(self, rel_dir: str) -> None:
        os.makedirs(self._abs(rel_dir), exist_ok=True)

    def open_write(self, rel: str, offset: int):
        if offset:
            f = open(self._abs(rel), "r+b")
            f.seek(offset)
            return f
        return open(self._abs(rel), "wb")

    def replace(self, src_rel: str, dst_rel: str) -> None:
        os.replace(self._abs(src_rel), self._abs(dst_rel))

    def set_mtime(self, rel: str, mtime: float) -> None:
        os.utime(self._abs(rel), (mtime, mtime))

    def remove(self, rel: str) -> None:
        os.remove(self._abs(rel))

    def remove_empty_dirs(self, rel_dir: str) -> None:
        while rel_dir:
            try:
                os.rmdir(self._abs(rel_dir))
            except OSError:
                return
            rel_dir = os.path.dirname(rel_dir)

