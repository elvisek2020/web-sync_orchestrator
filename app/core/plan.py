"""Porovnání dvou skenů a plán přenosu — čisté funkce, bez DB a bez FastAPI.

Kategorie:
  missing   soubor je jen ve zdroji → kopírovat
  conflict  soubor je na obou stranách, liší se velikost → přepsat (volba páru)
  extra     soubor je jen v cíli → smazat (volba páru, jen po potvrzení ve skriptu)
  same      shoda (velikost); čas změny se nepoužívá — mezi NASy se liší i u shodných souborů
Problémy se nepřenášejí ani nemažou, jen se ukážou (kolize názvů, exFAT, kódování).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Iterable

from .excludes import Excluder
from .keys import FileRec, has_bad_encoding

MISSING = "missing"
CONFLICT = "conflict"
EXTRA = "extra"

EXFAT_BAD_CHARS = set('\\:*?"<>|')
SAME_SAMPLE_SIZE = 20


@dataclass(slots=True)
class Item:
    key: str
    category: str
    src: FileRec | None = None
    tgt: FileRec | None = None
    problem: str | None = None

    @property
    def size(self) -> int:
        """Velikost, kterou položka zabere na disku (u extra velikost na cíli)."""
        if self.src is not None:
            return self.src.size
        return self.tgt.size if self.tgt is not None else 0

    @property
    def display(self) -> str:
        rec = self.src or self.tgt
        return rec.display if rec else self.key


@dataclass
class Comparison:
    missing: list[Item] = field(default_factory=list)
    conflict: list[Item] = field(default_factory=list)
    extra: list[Item] = field(default_factory=list)
    skipped: list[Item] = field(default_factory=list)
    direct: list[Item] = field(default_factory=list)     # označené k přímému přenosu (mimo plán na disk)
    problems: list[Item] = field(default_factory=list)
    same_count: int = 0
    same_size: int = 0
    excluded_count: int = 0
    source_count: int = 0
    source_size: int = 0
    target_count: int = 0
    target_size: int = 0
    same_sample: list[tuple[bytes, bytes]] = field(default_factory=list)  # (cesta na zdroji, cesta na cíli)


def exfat_problem(path: str) -> str | None:
    for seg in path.split("/"):
        if any(c in EXFAT_BAD_CHARS or ord(c) < 32 for c in seg):
            return "Název obsahuje znak, který exFAT nepovoluje"
        if seg.endswith((".", " ")):
            return "Název končí tečkou nebo mezerou (exFAT)"
    return None


def _index(files: Iterable[FileRec], excluder: Excluder, side_label: str, problems: list[Item]) -> tuple[dict[str, FileRec], int]:
    by_key: dict[str, FileRec] = {}
    collisions: dict[str, list[FileRec]] = {}
    excluded = 0
    for rec in files:
        if excluder.excluded(rec.key):
            excluded += 1
            continue
        if rec.key in collisions:
            collisions[rec.key].append(rec)
            continue
        if rec.key in by_key:
            collisions[rec.key] = [by_key.pop(rec.key), rec]
            continue
        by_key[rec.key] = rec
    for key, recs in collisions.items():
        for rec in recs:
            is_src = side_label == "zdroj"
            problems.append(Item(
                key=key, category=MISSING if is_src else EXTRA,
                src=rec if is_src else None, tgt=None if is_src else rec,
                problem=f"Kolize názvů ({side_label}): {len(recs)} soubory se po normalizaci jmenují stejně",
            ))
    return by_key, excluded


def compare(source: Iterable[FileRec], target: Iterable[FileRec], excluder: Excluder,
            skips: set[str] | None = None, direct: set[str] | None = None) -> Comparison:
    skips = skips or set()
    direct = direct or set()
    cmp = Comparison()
    src, ex_s = _index(source, excluder, "zdroj", cmp.problems)
    tgt, ex_t = _index(target, excluder, "cíl", cmp.problems)
    cmp.excluded_count = ex_s + ex_t
    cmp.source_count, cmp.source_size = len(src), sum(r.size for r in src.values())
    cmp.target_count, cmp.target_size = len(tgt), sum(r.size for r in tgt.values())

    items: list[Item] = []
    for key in sorted(src.keys() | tgt.keys()):
        s, t = src.get(key), tgt.get(key)
        if s is not None and t is not None:
            if s.size == t.size:
                cmp.same_count += 1
                cmp.same_size += s.size
                if len(cmp.same_sample) < SAME_SAMPLE_SIZE:
                    cmp.same_sample.append((s.path, t.path))
                continue
            item = Item(key, CONFLICT, s, t)
        elif s is not None:
            item = Item(key, MISSING, s, None)
        else:
            item = Item(key, EXTRA, None, t)
        if has_bad_encoding(key):
            item.problem = "Název souboru není platné UTF-8"
        elif item.category != EXTRA:
            item.problem = exfat_problem(item.src.display)
        items.append(item)

    # Na exFAT se nesmí potkat dva názvy lišící se jen velikostí písmen.
    folded: dict[str, list[Item]] = {}
    for item in items:
        if item.category != EXTRA and item.problem is None:
            folded.setdefault(item.key.casefold(), []).append(item)
    for group in folded.values():
        if len(group) > 1:
            for item in group:
                item.problem = "Liší se od jiného souboru jen velikostí písmen (exFAT)"

    buckets = {MISSING: cmp.missing, CONFLICT: cmp.conflict, EXTRA: cmp.extra}
    for item in items:
        if item.problem:
            cmp.problems.append(item)
        elif item.key in direct:
            cmp.direct.append(item)
        elif item.key in skips:
            cmp.skipped.append(item)
        else:
            buckets[item.category].append(item)
    cmp.problems.sort(key=lambda i: i.key)
    return cmp


@dataclass
class PairPlan:
    pair_id: int
    comparison: Comparison
    on_disk: bool
    include_conflicts: bool
    include_extra: bool
    transfer: list[Item] = field(default_factory=list)   # kandidáti na disk (missing + případně conflict)
    selected: list[Item] = field(default_factory=list)   # vešlo se na disk
    deferred: list[Item] = field(default_factory=list)   # nevešlo se → příští přenos
    deletions: list[Item] = field(default_factory=list)  # smazat na cíli (disk → NAS)
    deletion_blocked: str | None = None

    @property
    def selected_size(self) -> int:
        return sum(i.size for i in self.selected)

    @property
    def deferred_size(self) -> int:
        return sum(i.size for i in self.deferred)

    @property
    def transfer_size(self) -> int:
        return sum(i.size for i in self.transfer)

    @property
    def deletions_size(self) -> int:
        return sum(i.size for i in self.deletions)

    def plan_hash(self) -> str:
        h = hashlib.sha256()
        for item in sorted(self.selected, key=lambda i: i.src.path):
            h.update(b"C\0" + item.src.path + b"\0" + str(item.src.size).encode() + b"\n")
        for item in sorted(self.deletions, key=lambda i: i.tgt.path):
            h.update(b"D\0" + item.tgt.path + b"\n")
        return h.hexdigest()[:12]


def build_plan(pair_id: int, comparison: Comparison, *, on_disk: bool, include_conflicts: bool, include_extra: bool) -> PairPlan:
    plan = PairPlan(pair_id, comparison, on_disk, include_conflicts, include_extra)
    plan.transfer = sorted(
        comparison.missing + (comparison.conflict if include_conflicts else []),
        key=lambda i: i.key,
    )
    if include_extra:
        if comparison.source_count == 0:
            plan.deletion_blocked = "Zdrojový sken je prázdný — mazání na cíli je zablokované."
        else:
            plan.deletions = list(comparison.extra)
    return plan


def allocate(plans_in_order: list[PairPlan], capacity: int | None) -> int:
    """Rozdělí kapacitu disku mezi páry zahrnuté do přenosu (v pořadí). Vrací zbývající kapacitu.

    Uvnitř páru se jde podle cesty a použije se first-fit: co se nevejde, přeskočí se
    a zkouší se další soubory. Bez kapacity (None/0) se vybere všechno.
    """
    remaining = capacity if capacity and capacity > 0 else None
    for plan in plans_in_order:
        plan.selected, plan.deferred = [], []
        if not plan.on_disk:
            continue
        for item in plan.transfer:
            if remaining is None:
                plan.selected.append(item)
            elif item.size <= remaining:
                plan.selected.append(item)
                remaining -= item.size
            else:
                plan.deferred.append(item)
    return remaining if remaining is not None else 0
