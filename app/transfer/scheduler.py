"""Plánovač: denní automatická aktualizace všech párů a naplánovaný přímý přenos v časovém okně.

Automatická aktualizace: jednou denně v zadaný čas spustí „Aktualizovat vše“ (zmeškaný termín
po restartu dožene nejpozději do hodiny).

Přímý přenos: v časovém okně spouští naplánované páry, jeden po druhém.

Každých pár desítek sekund (a hned po naplánování) se podívá, jestli je okno otevřené. Když ano
a žádný přímý přenos neběží, spustí první naplánovaný pár (v pořadí párů). Přenos sám po konci
okna další soubor nezačne a skončí jako „pozastavený“; pár zůstane naplánovaný na další okno.
Když je přeneseno všechno (nebo uživatel přenos zruší), plán se zruší. Po selhání (např. NAS2
nedostupný) se to v okně zkusí znovu za RETRY_AFTER.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta

from app import db
from app.config import settings

from .runner import transfer_runner
from .window import REFRESH_LAST, get_window, refresh_due

logger = logging.getLogger("sync.scheduler")

TICK_SECONDS = 30
RETRY_AFTER = timedelta(minutes=15)


class Scheduler:
    def __init__(self) -> None:
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not settings.scheduler_enabled or (self._thread and self._thread.is_alive()):
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def wake(self) -> None:
        """Podívat se hned (po naplánování nebo změně okna), ne až za TICK_SECONDS."""
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001 — plánovač nesmí spadnout
                logger.exception("Plánovač: kontrola selhala")
            self._wake.wait(TICK_SECONDS)
            self._wake.clear()

    def refresh_tick(self, now: datetime | None = None) -> bool:
        """Automatická aktualizace: v denní čas spustí sken všech párů (jednou za den)."""
        from app.apps.pairs import db as pairs_db
        from app.scan.runner import runner

        day = refresh_due(now or datetime.now())
        if day is None:
            return False
        db.set_setting(REFRESH_LAST, day)
        pairs = pairs_db.list_pairs()
        for pair in pairs:
            runner.start_pair(pair["id"])          # pár, který právě přenáší, runner přeskočí
        logger.info("Plánovač: automatická aktualizace %d párů", len(pairs))
        return True

    def tick(self, now: datetime | None = None) -> int | None:
        """Jedna kontrola; vrátí id spuštěného přenosu, nebo None."""
        from app.apps.pairs import db as pairs_db
        from app.apps.pairs.state import load_overview

        now = now or datetime.now()
        self.refresh_tick(now)
        window = get_window()
        if window is None or not window.contains(now) or transfer_runner.direct_running():
            return None
        scheduled = [p for p in pairs_db.list_pairs() if p["scheduled"]]
        if not scheduled:
            return None
        overview = load_overview()
        for pair in scheduled:
            failed_at = pairs_db.last_direct_failure(pair["id"])
            if failed_at and now - datetime.fromisoformat(failed_at) < RETRY_AFTER:
                continue
            st = overview.get(pair["id"])
            if st is None or not st.plan or st.busy or st.transferring:
                continue
            items = st.plan.comparison.direct
            if not st.direct_supported or not items:
                pairs_db.set_scheduled(pair["id"], False)       # není co přenést → plán hotový
                continue
            transfer_id = transfer_runner.start(st.pair, items, st.target.current["id"], window=window)
            if transfer_id:
                logger.info("Plánovač: pár %s — přímý přenos v okně %s", pair["name"], window.label)
                return transfer_id
        return None


scheduler = Scheduler()
