"""Cesty souborů: skutečné bajty pro skript vs. porovnávací klíč.

`path` je relativní cesta přesně tak, jak existuje na disku (bajty) — s ní pracuje skript.
`key` je NFC normalizovaná textová podoba — podle ní se páruje zdroj s cílem, protože
macOS/SMB ukládá diakritiku rozloženě (NFD) a Linux složeně (NFC).
"""
from __future__ import annotations

import os
import unicodedata
from dataclasses import dataclass

REPLACEMENT = "�"


@dataclass(frozen=True, slots=True)
class FileRec:
    path: bytes
    key: str
    size: int
    mtime: float

    @property
    def display(self) -> str:
        return self.path.decode("utf-8", "replace")


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def key_from_local(rel: str) -> str:
    """Klíč z lokální cesty (str z os.* se surrogateescape). Neplatné UTF-8 → znak �."""
    clean = os.fsencode(rel).decode("utf-8", "replace")
    return nfc(clean)


def fix_mojibake(name: str) -> str:
    """Oprava dvojitě kódovaného UTF-8 (převzato ze staré verze ssh_scan.py).

    Některé NASy vrací přes SFTP UTF-8 bajty přečtené jako cp1252/latin-1.
    Používá se jen pro porovnávací klíč, nikdy pro skutečnou cestu.
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


def key_from_remote(rel: str) -> str:
    return "/".join(nfc(fix_mojibake(seg)) for seg in rel.split("/"))


def has_bad_encoding(key: str) -> bool:
    return REPLACEMENT in key
