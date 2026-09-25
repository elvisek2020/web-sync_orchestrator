"""Časové okno pro naplánovaný přímý přenos (např. 22:00–06:00, každý den).

Okno je jedno pro všechny páry a uloží se v nastavení jako „HH:MM-HH:MM“. Když je začátek
později než konec, okno přechází přes půlnoc (22:00–06:00 = večer do půlnoci + ráno do šesti).
Čas se bere z kontejneru (TZ v docker-compose).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from app import db

SETTING = "transfer_window"
_HHMM = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


@dataclass(frozen=True)
class Window:
    start: int    # minuty od půlnoci
    end: int

    @property
    def label(self) -> str:
        return f"{_fmt(self.start)}–{_fmt(self.end)}"

    def contains(self, now: datetime) -> bool:
        m = now.hour * 60 + now.minute
        if self.start < self.end:
            return self.start <= m < self.end
        return m >= self.start or m < self.end          # přes půlnoc

    def end_after(self, now: datetime) -> datetime:
        """Konec okna, ve kterém `now` leží (nebo nejbližší další konec)."""
        return _next_at(now, self.end)

    def next_start(self, now: datetime) -> datetime:
        return _next_at(now, self.start)


def _fmt(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _next_at(now: datetime, minutes: int) -> datetime:
    at = now.replace(hour=minutes // 60, minute=minutes % 60, second=0, microsecond=0)
    return at if at > now else at + timedelta(days=1)


def parse_time(value: str) -> int | None:
    m = _HHMM.match((value or "").strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def parse(value: str) -> Window | None:
    start, _, end = (value or "").partition("-")
    s, e = parse_time(start), parse_time(end)
    if s is None or e is None or s == e:
        return None
    return Window(s, e)


# --- automatická aktualizace: jeden čas denně pro „Aktualizovat vše“ ---

REFRESH_SETTING = "auto_refresh_time"
REFRESH_LAST = "auto_refresh_last"        # datum, kdy už proběhla (aby běžela jen jednou denně)
REFRESH_GRACE = 60                        # minut: zmeškaný termín (restart) se ještě dožene


def get_refresh_time() -> int | None:
    return parse_time(db.get_setting(REFRESH_SETTING, ""))


def refresh_label(minutes: int | None) -> str:
    return _fmt(minutes) if minutes is not None else ""


def set_refresh_time(value: str) -> int | None:
    """Uloží čas automatické aktualizace; prázdný ji vypne. Neplatný → ValueError."""
    if not (value or "").strip():
        db.set_setting(REFRESH_SETTING, "")
        return None
    minutes = parse_time(value)
    if minutes is None:
        raise ValueError("Neplatný čas")
    db.set_setting(REFRESH_SETTING, _fmt(minutes))
    # termín, který už dnes minul, se po uložení nedohání — první aktualizace až v nejbližší zadaný čas
    db.set_setting(REFRESH_LAST, "")
    db.set_setting(REFRESH_LAST, refresh_due(datetime.now()) or "")
    return minutes


def refresh_due(now: datetime) -> str | None:
    """Datum termínu, který je právě na řadě a ještě neproběhl (jinak None)."""
    at = get_refresh_time()
    if at is None:
        return None
    late = (now.hour * 60 + now.minute - at) % (24 * 60)      # minut po termínu (i přes půlnoc)
    if late >= REFRESH_GRACE:
        return None
    day = (now - timedelta(minutes=late)).date().isoformat()
    return None if db.get_setting(REFRESH_LAST, "") == day else day


def get_window() -> Window | None:
    return parse(db.get_setting(SETTING, ""))


def set_window(start: str, end: str) -> Window | None:
    """Uloží okno; prázdné časy okno zruší. Neplatné (nebo začátek = konec) → ValueError."""
    if not (start or "").strip() and not (end or "").strip():
        db.set_setting(SETTING, "")
        return None
    s, e = parse_time(start), parse_time(end)
    if s is None or e is None or s == e:
        raise ValueError("Neplatné okno")
    window = Window(s, e)
    db.set_setting(SETTING, f"{_fmt(s)}-{_fmt(e)}")
    return window
