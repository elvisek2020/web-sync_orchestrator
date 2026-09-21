"""Vzory pro vynechání souborů a složek.

Vzor bez „/“ se porovná s každým segmentem cesty — vyřadí soubor i celou složku
(`@eaDir`, `*.tmp`). Vzor s „/“ se porovná s celou relativní cestou
(`Naked Attraction CZ/*`). Porovnání nerozlišuje velikost písmen.
Na rozdíl od staré verze se nehledá podřetězec: `.git` nevyřadí `.gitignore`.
"""
from __future__ import annotations

from fnmatch import fnmatchcase

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


class Excluder:
    def __init__(self, patterns: list[str]):
        self.patterns = list(patterns)
        self._segment = [p.lower() for p in patterns if "/" not in p]
        self._path = [p.strip("/").lower() for p in patterns if "/" in p]

    def _segment_excluded(self, segment: str) -> bool:
        s = segment.lower()
        return any(fnmatchcase(s, p) for p in self._segment)

    def excluded_name(self, name: str) -> bool:
        """Pro prořezávání během skenu: vyhovuje samotný název položky?"""
        return self._segment_excluded(name)

    def excluded(self, key: str) -> bool:
        if any(self._segment_excluded(seg) for seg in key.split("/")):
            return True
        low = key.lower()
        return any(fnmatchcase(low, p) for p in self._path)
