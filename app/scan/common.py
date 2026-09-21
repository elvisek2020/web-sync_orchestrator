"""Společné typy skenerů: průběh, zrušení, chyby."""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field


def cz_items(count: int) -> str:
    word = "položka" if count == 1 else "položky" if 2 <= count <= 4 else "položek"
    return f"{count} {word}"


class ScanError(Exception):
    """Sken nelze dokončit spolehlivě — žádné tiché přeskakování složek."""


class ScanCancelled(Exception):
    pass


@dataclass
class Progress:
    files: int = 0
    bytes: int = 0
    dirs: int = 0
    current: str = ""
    started: float = field(default_factory=time.monotonic)
    cancel: threading.Event = field(default_factory=threading.Event)
    log_lines: deque = field(default_factory=lambda: deque(maxlen=2000))

    def log(self, message: str) -> None:
        self.log_lines.append(f"{time.strftime('%H:%M:%S')} {message}")

    def check_cancel(self) -> None:
        if self.cancel.is_set():
            raise ScanCancelled("Sken byl zrušen.")

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def log_text(self) -> str:
        return "\n".join(self.log_lines)
