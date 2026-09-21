"""Sken lokálně připojené složky (NAS1 v kontejneru)."""
from __future__ import annotations

import os
import stat
from pathlib import Path

from app.core.excludes import Excluder
from app.core.keys import FileRec, key_from_local

from .common import Progress, ScanError, cz_items


def scan_local(root: Path, excluder: Excluder, progress: Progress, *, allow_empty: bool) -> list[FileRec]:
    if not root.exists():
        raise ScanError(f"Složka neexistuje: {root}")
    if not root.is_dir():
        raise ScanError(f"Cesta není složka: {root}")

    progress.log(f"Skenuji lokálně: {root}")
    records: list[FileRec] = []
    skipped_other = 0
    stack: list[str] = [""]
    while stack:
        progress.check_cancel()
        rel_dir = stack.pop()
        abs_dir = os.path.join(root, rel_dir) if rel_dir else str(root)
        progress.current = rel_dir or "/"
        try:
            with os.scandir(abs_dir) as it:
                entries = list(it)
        except OSError as e:
            raise ScanError(f"Nelze přečíst složku „{rel_dir or '/'}“: {e}") from e
        progress.dirs += 1
        if rel_dir.count("/") < 1:
            progress.log(f"Složka {rel_dir or '/'} ({cz_items(len(entries))})")

        for entry in entries:
            name = entry.name
            rel = f"{rel_dir}/{name}" if rel_dir else name
            if excluder.excluded_name(key_from_local(name)):
                continue
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError as e:
                raise ScanError(f"Nelze zjistit údaje o „{rel}“: {e}") from e
            if stat.S_ISLNK(st.st_mode):
                progress.log(f"Přeskakuji symbolický odkaz: {rel}")
                continue
            if stat.S_ISDIR(st.st_mode):
                stack.append(rel)
            elif stat.S_ISREG(st.st_mode):
                key = key_from_local(rel)
                if excluder.excluded(key):
                    continue
                records.append(FileRec(os.fsencode(rel), key, st.st_size, st.st_mtime))
                progress.files += 1
                progress.bytes += st.st_size
            else:
                skipped_other += 1

    if skipped_other:
        progress.log(f"Přeskočeno {skipped_other} speciálních položek (zařízení, sockety…)")
    if not records and not allow_empty:
        raise ScanError(
            f"Ve složce {root} není žádný soubor. Je NAS správně připojený? "
            "(Prázdný zdroj by vedl k mazání všeho na cíli.)"
        )
    progress.log(f"Hotovo: {len(records)} souborů, {progress.dirs} složek")
    return records
