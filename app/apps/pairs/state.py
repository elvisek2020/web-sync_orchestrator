"""Stav párů pro UI: poslední skeny, běžící skeny, porovnání a plán s kapacitou disku."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app import db
from app.core.plan import PairPlan, allocate, build_plan, compare
from app.scan.common import Progress
from app.scan.runner import pair_excluder, runner

from . import db as pairs_db

AGE_WARNING_HOURS = 24


@dataclass
class SideState:
    side: str
    current: dict | None = None   # poslední úspěšný sken (platná data)
    running: dict | None = None   # čeká ve frontě / běží
    progress: Progress | None = None
    failed: dict | None = None    # neúspěšný pokus novější než platný sken


@dataclass
class PairState:
    pair: dict
    source: SideState
    target: SideState
    plan: PairPlan | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def busy(self) -> bool:
        return bool(self.source.running or self.target.running)


@dataclass
class Overview:
    pairs: list[PairState]
    capacity: int
    allocated: int
    deferred: int

    @property
    def busy(self) -> bool:
        return any(p.busy for p in self.pairs)

    def get(self, pair_id: int) -> PairState | None:
        return next((p for p in self.pairs if p.pair["id"] == pair_id), None)


def get_capacity() -> int:
    try:
        return int(db.get_setting("disk_capacity", "0") or 0)
    except ValueError:
        return 0


def _side_state(side: str, scans: list[dict]) -> SideState:
    state = SideState(side)
    for scan in scans:  # od nejnovějšího
        if scan["side"] != side:
            continue
        if scan["status"] in ("queued", "running"):
            job = runner.active(scan["id"])
            if job is None:
                pairs_db.mark_dead_scan(scan["id"])
                scan = dict(scan, status="failed", error=scan.get("error") or "Sken přestal běžet.")
            elif state.running is None:
                state.running, state.progress = scan, job.progress
                continue
        if scan["status"] == "done" and state.current is None:
            state.current = scan
        elif scan["status"] in ("failed", "cancelled") and state.current is None and state.failed is None:
            state.failed = scan
    if state.running:
        state.failed = None  # nový pokus běží — starý neúspěch už nehlásit
    return state


def _hours_between(a: str, b: str) -> float:
    return abs((datetime.fromisoformat(a) - datetime.fromisoformat(b)).total_seconds()) / 3600


def load_overview() -> Overview:
    states: list[PairState] = []
    for pair in pairs_db.list_pairs():
        scans = pairs_db.scans_for_pair(pair["id"])
        st = PairState(pair, _side_state("source", scans), _side_state("target", scans))
        src, tgt = st.source.current, st.target.current
        if src and tgt:
            comparison = compare(
                pairs_db.load_files(src["id"]), pairs_db.load_files(tgt["id"]),
                pair_excluder(pair), pairs_db.skips_for_pair(pair["id"]),
            )
            st.plan = build_plan(
                pair["id"], comparison, on_disk=bool(pair["on_disk"]),
                include_conflicts=bool(pair["include_conflicts"]), include_extra=bool(pair["include_extra"]),
            )
            hours = _hours_between(src["finished_at"], tgt["finished_at"])
            if hours > AGE_WARNING_HOURS:
                st.warnings.append(f"Skeny zdroje a cíle se liší stářím o {hours:.0f} h — zvažte Aktualizovat.")
        for side in (st.source, st.target):
            if side.failed:
                label = "zdroje" if side.side == "source" else "cíle"
                st.warnings.append(f"Poslední sken {label} se nepovedl — platí starší data.")
        if st.plan and st.plan.deletion_blocked:
            st.warnings.append(st.plan.deletion_blocked)
        states.append(st)

    capacity = get_capacity()
    plans = [s.plan for s in states if s.plan]
    allocate(plans, capacity)
    allocated = sum(p.selected_size for p in plans)
    deferred = sum(p.deferred_size for p in plans)
    return Overview(states, capacity, allocated, deferred)
