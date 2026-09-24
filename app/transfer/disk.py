"""Přenosový disk připojený do kontejneru (DISK_PATH): volné místo a kontrola před přenosem na disk.

Soubory páru leží na disku v <disk>/<slug>/ (stejně jako při kroku to-disk skriptu), skript
v kořeni disku a manifest .sync-plan ve složce páru — krok to-nas na NAS2 pak funguje beze změny.
"""
from __future__ import annotations

import os
from pathlib import Path

from app.config import settings
from app.core.plan import Item

from .targets import as_str, part_name

DISK_MIN_PLAUSIBLE = 20 * 10**9  # menší „disk“ je nejspíš prázdná složka na systémovém oddílu NASu
DISK_RESERVE_RATIO = 0.01        # rezerva: exFAT zabírá víc než součet velikostí, Synology zapisuje @eaDir
DISK_RESERVE_MIN = 10**9         # nejméně 1 GB

MANIFEST = ".sync-plan"


def usable_capacity(free: int) -> int:
    """Kapacita pro plán = volné místo minus rezerva, zaokrouhleno dolů na celé GB."""
    reserve = max(int(free * DISK_RESERVE_RATIO), DISK_RESERVE_MIN)
    return max(free - reserve, 0) // 10**9 * 10**9


def disk_info() -> dict:
    """Volné místo na přenosovém disku a jestli na něj jde zapisovat."""
    path = settings.disk_path
    info = {"path": str(path), "mounted": False, "writable": False, "free": 0, "total": 0, "usable": 0,
            "suspicious": False}
    if not path.is_dir():
        return info
    try:
        st = os.statvfs(path)
    except OSError:
        return info
    info.update(mounted=True, free=st.f_bavail * st.f_frsize, total=st.f_blocks * st.f_frsize)
    info["usable"] = usable_capacity(info["free"])
    info["suspicious"] = info["total"] < DISK_MIN_PLAUSIBLE
    info["writable"] = os.access(path, os.W_OK)   # připojení :ro → False
    return info


def pair_dir(pair: dict) -> Path:
    return settings.disk_path / pair["slug"]


def bytes_needed(items: list[Item], root: Path) -> int:
    """Kolik místa přenos ještě potřebuje: celé soubory už na disku se nepočítají, rozpracované jen zbytkem."""
    need = 0
    for item in items:
        rel = as_str(item.src.path)
        try:
            if os.stat(root / rel).st_size == item.src.size:
                continue
        except OSError:
            pass
        try:
            done = min(os.stat(root / part_name(rel)).st_size, item.src.size)
        except OSError:
            done = 0
        need += item.src.size - done
    return need


def disk_problem(items: list[Item], root: Path) -> str | None:
    """Kód hlášky, proč přenos na disk nejde spustit; None = lze."""
    info = disk_info()
    if not info["mounted"]:
        return "disk_not_mounted"
    if not info["writable"]:
        return "disk_readonly"
    if info["suspicious"]:
        return "disk_suspicious"
    if bytes_needed(items, root) > info["free"]:
        return "disk_full"
    return None
