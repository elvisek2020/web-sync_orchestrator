"""Vzory pro vynechání souborů a složek.

Vzor bez „/“ se porovná s každým segmentem cesty — vyřadí soubor i celou složku
(`@eaDir`, `*.tmp`). Vzor s „/“ se porovná s celou relativní cestou
(`Naked Attraction CZ/*`). Porovnání nerozlišuje velikost písmen.
Na rozdíl od staré verze se nehledá podřetězec: `.git` nevyřadí `.gitignore`.
"""
from __future__ import annotations

import fnmatch
import re

DEFAULT_EXCLUDE_PATTERNS = [
    # macOS / Windows
    ".DS_Store",
    "._*",
    ".AppleDouble",
    "Thumbs.db",
    "desktop.ini",
    ".Trash*",
    # dočasné soubory
    "*.tmp",
    "*.swp",
    "*.bak",
    # verzovací systémy
    ".git",
    ".svn",
    ".hg",
    # Synology
    "@eaDir",
    "#recycle",
    "*@SynoEAStream",
    "*@SynoResource",
    "*@SynoStream",
    # QNAP
    "@Recycle",
    "@Recently-Snapshot",
    ".@__thumb",
    # alternativní datové proudy (SMB)
    ".streams",
    "*:$DATA",
]


# Vždy vynechané (nejde vypnout v nastavení): rozpracované soubory přímého přenosu.
INTERNAL_EXCLUDE_PATTERNS = [".*.syncpart"]


def parse_patterns(text: str | None) -> list[str]:
    """Jeden vzor na řádek (čárky se také berou jako oddělovač)."""
    if not text:
        return []
    out: list[str] = []
    for line in text.replace(",", "\n").splitlines():
        p = line.strip()
        if p and p not in out:
            out.append(p)
    return out


def _compile(patterns: list[str]) -> re.Pattern | None:
    # Všechny vzory v jednom regulárním výrazu — o řád rychlejší než fnmatch pro každý zvlášť.
    return re.compile("|".join(fnmatch.translate(p) for p in patterns)) if patterns else None


class Excluder:
    def __init__(self, patterns: list[str]):
        self.patterns = list(patterns)
        self._segment_re = _compile([p.lower() for p in patterns if "/" not in p])
        self._path_re = _compile([p.strip("/").lower() for p in patterns if "/" in p])
        # Názvy složek se v cestách opakují tisíckrát → výsledek pro segment si pamatujeme.
        self._segment_cache: dict[str, bool] = {}

    def _segment_excluded(self, segment: str) -> bool:
        hit = self._segment_cache.get(segment)
        if hit is None:
            hit = bool(self._segment_re and self._segment_re.match(segment.lower()))
            self._segment_cache[segment] = hit
        return hit

    def excluded_name(self, name: str) -> bool:
        """Pro prořezávání během skenu: vyhovuje samotný název položky?"""
        return self._segment_excluded(name)

    def excluded(self, key: str) -> bool:
        if any(self._segment_excluded(seg) for seg in key.split("/")):
            return True
        return bool(self._path_re and self._path_re.match(key.lower()))
