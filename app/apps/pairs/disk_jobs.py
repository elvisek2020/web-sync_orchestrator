"""Přenos na disk: spuštění s kontrolami a fronta párů.

Na disk kopíruje vždy jen jeden pár. Když se kopíruje, další páry jde zařadit do fronty
(`pairs.disk_queued` = čas zařazení); plánovač je spouští jeden po druhém, jakmile se disk uvolní.
Co se zkopíruje, se počítá až při spuštění — výběr se ořízne podle skutečného volného místa
na disku (kapacita v plánu nepočítá soubory, které už na disku leží z předchozího páru).
"""
from __future__ import annotations

import logging
from dataclasses import replace

from app.common import FLASH_MESSAGES
from app.config import settings
from app.core.plan import Item, PairPlan
from app.core.script import generate_script, script_filename
from app.transfer import disk
from app.transfer.runner import transfer_runner

from . import db as pairs_db
from .state import PairState, load_overview

logger = logging.getLogger("sync.disk")


def side_desc(pair: dict, side: str) -> str:
    host = pair[f"{side}_host_name"]
    path = pair[f"{side}_path"]
    if host:
        return f"{host}:{path}"
    return f"{settings.local_root}/{path}".rstrip("/")


def script_for(pair: dict, plan: PairPlan) -> str:
    return generate_script(
        pair_name=pair["name"], slug=pair["slug"], plan=plan,
        source_desc=side_desc(pair, "source"), target_desc=side_desc(pair, "target"),
    )


def _fits_free_space(items: list[Item], pair: dict) -> list[Item]:
    """First-fit podle skutečného volného místa (minus rezerva); soubory už na disku se nepočítají."""
    root = disk.pair_dir(pair)
    remaining = disk.disk_info()["free"] - disk.DISK_RESERVE
    selected = []
    for item in items:
        need = disk.bytes_needed([item], root)
        if need <= remaining:
            selected.append(item)
            remaining -= need
    return selected


def start(st: PairState) -> str:
    """Spustí přenos na disk; vrátí kód hlášky (disk_started = spuštěno)."""
    if not st.plan:
        return "no_plan"
    if not st.plan.on_disk:
        return "not_on_disk"
    if st.busy or st.transferring:
        return "transfer_busy"
    if not st.plan.selected:
        return "disk_nothing"
    if transfer_runner.disk_running():
        return "disk_busy"
    root = disk.pair_dir(st.pair)
    problem = disk.disk_problem([], root)
    if problem:
        return problem
    items = _fits_free_space(st.plan.selected, st.pair)
    if not items:
        return "disk_full"
    pair = st.pair
    started = transfer_runner.start_disk(
        pair, replace(st.plan, selected=items), script_name=script_filename(pair["slug"]),
        make_script=lambda plan: script_for(pair, plan),
    )
    return "disk_started" if started else "disk_busy"


def start_next() -> int | None:
    """Spustí další pár z fronty, je-li disk volný. Vrátí id páru, který se spustil.

    Pár, který se právě skenuje nebo přenáší, počká. Pár, který spustit nejde (disk plný, odpojený,
    není co kopírovat…), z fronty vypadne a do karty Poslední přenos na disk se zapíše proč.
    """
    if transfer_runner.disk_running():
        return None
    queue = pairs_db.disk_queue()
    if not queue:
        return None
    overview = load_overview()
    for pair in queue:
        st = overview.get(pair["id"])
        if st and (st.busy or st.transferring):
            continue
        pairs_db.set_disk_queued(pair["id"], False)
        code = start(st) if st else "no_plan"
        if code == "disk_started":
            logger.info("Fronta na disk: spuštěn pár %s", pair["name"])
            return pair["id"]
        reason = FLASH_MESSAGES.get(code, ("error", code))[1]
        logger.warning("Fronta na disk: pár %s se nespustil — %s", pair["name"], reason)
        _record_failure(pair["id"], f"Z fronty se nespustil: {reason}")
    return None


def _record_failure(pair_id: int, error: str) -> None:
    tid = pairs_db.create_transfer(pair_id, kind="disk", files_total=0, bytes_total=0, delete_total=0)
    pairs_db.finish_transfer(tid, status="failed", files_done=0, bytes_done=0, deleted=0, failed=0,
                             error=error, log=error)
