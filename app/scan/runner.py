"""Běh skenů na pozadí — jediný background job aplikace.

Zásady (poučení ze zasekávání staré verze):
- sken sbírá soubory do paměti a DB během procházení nedrží;
- výsledek se zapíše JEDNOU krátkou transakcí (BEGIN IMMEDIATE) — buď celý, nebo vůbec;
- selhaný/zrušený sken nechá platný předchozí úspěšný sken;
- stav se zapíše vždy (try/finally); po restartu se nedokončené skeny označí jako selhané;
- nejvýš jeden sken na jednoho hosta najednou (NAS1 lokálně, každý SSH host zvlášť).
"""
from __future__ import annotations

import logging
import threading
import traceback
from dataclasses import dataclass

from sqlalchemy import text

from app import db
from app.config import settings
from app.core.excludes import DEFAULT_EXCLUDE_PATTERNS, Excluder, parse_patterns

from .common import Progress, ScanCancelled, ScanError
from .local import scan_local
from .sftp import scan_sftp

logger = logging.getLogger("sync.runner")

INSERT_CHUNK = 5000


@dataclass
class ActiveScan:
    scan_id: int
    pair_id: int
    side: str
    progress: Progress
    thread: threading.Thread | None = None


def pair_excluder(pair: dict) -> Excluder:
    defaults = parse_patterns(db.get_setting("default_excludes", "\n".join(DEFAULT_EXCLUDE_PATTERNS)))
    return Excluder(defaults + parse_patterns(pair.get("exclude_patterns")))


class ScanRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[int, ActiveScan] = {}
        self._host_locks: dict[str, threading.Lock] = {}

    # --- dotazy pro UI ---

    def active(self, scan_id: int) -> ActiveScan | None:
        with self._lock:
            return self._active.get(scan_id)

    def is_alive(self, scan_id: int) -> bool:
        return self.active(scan_id) is not None

    def any_running(self) -> bool:
        with self._lock:
            return bool(self._active)

    # --- spouštění ---

    def start_pair(self, pair_id: int) -> list[int]:
        return [sid for side in ("source", "target") if (sid := self.start(pair_id, side))]

    def start(self, pair_id: int, side: str) -> int | None:
        pair = db.query_one("SELECT * FROM pairs WHERE id = :id", {"id": pair_id})
        if not pair:
            return None
        with self._lock:
            if any(a.pair_id == pair_id and a.side == side for a in self._active.values()):
                return None  # už běží nebo čeká ve frontě
            scan_id = db.execute(
                "INSERT INTO scans (pair_id, side, status, created_at) VALUES (:p, :s, 'queued', :now)",
                {"p": pair_id, "s": side, "now": db.now_iso()},
            )
            job = ActiveScan(scan_id, pair_id, side, Progress())
            job.thread = threading.Thread(target=self._run, args=(job,), daemon=True, name=f"scan-{scan_id}")
            self._active[scan_id] = job
        job.thread.start()
        logger.info("Sken #%d zařazen (pár %d, %s)", scan_id, pair_id, side)
        return scan_id

    def cancel(self, scan_id: int) -> bool:
        job = self.active(scan_id)
        if job:
            job.progress.cancel.set()
            return True
        return False

    def cancel_pair(self, pair_id: int) -> int:
        """Zruší všechny běžící i čekající skeny páru. Vrací jejich počet."""
        with self._lock:
            jobs = [a for a in self._active.values() if a.pair_id == pair_id]
        for job in jobs:
            job.progress.cancel.set()
        return len(jobs)

    def _host_lock(self, key: str) -> threading.Lock:
        with self._lock:
            return self._host_locks.setdefault(key, threading.Lock())

    # --- samotný běh ---

    def _run(self, job: ActiveScan) -> None:
        status, error = "failed", None
        progress = job.progress
        try:
            pair = db.query_one("SELECT * FROM pairs WHERE id = :id", {"id": job.pair_id})
            if not pair:
                raise ScanError("Pár mezitím smazán.")
            host_id = pair[f"{job.side}_host_id"]
            path = pair[f"{job.side}_path"]
            host = db.query_one("SELECT * FROM hosts WHERE id = :id", {"id": host_id}) if host_id else None
            if host_id and not host:
                raise ScanError("SSH host páru neexistuje.")

            lock = self._host_lock(f"ssh:{host_id}" if host_id else "local")
            while not lock.acquire(timeout=1):
                progress.check_cancel()
            try:
                db.execute(
                    "UPDATE scans SET status = 'running', started_at = :now WHERE id = :id",
                    {"now": db.now_iso(), "id": job.scan_id},
                )
                excluder = pair_excluder(pair)
                allow_empty = job.side == "target"  # prázdný cíl je normální (první synchronizace)
                if host:
                    records = scan_sftp(host, path, excluder, progress, allow_empty=allow_empty)
                else:
                    root = settings.local_root / path.strip("/")
                    records = scan_local(root, excluder, progress, allow_empty=allow_empty)
                progress.check_cancel()
            finally:
                lock.release()

            self._commit_success(job, records)
            status = "done"
        except ScanCancelled as e:
            status, error = "cancelled", str(e)
        except ScanError as e:
            error = str(e)
        except Exception as e:  # neočekávaná chyba — celý traceback do DB
            error = f"{e}\n\n{traceback.format_exc()}"
        finally:
            if status != "done":
                self._finish_failed(job, status, error)
            with self._lock:
                self._active.pop(job.scan_id, None)
            logger.info(
                "Sken #%d (pár %d, %s) skončil: %s, %d souborů, %.0f s%s",
                job.scan_id, job.pair_id, job.side, status, progress.files, progress.elapsed,
                f" — {error.splitlines()[0]}" if error else "",
            )

    def _commit_success(self, job: ActiveScan, records) -> None:
        progress = job.progress
        progress.log(f"Ukládám {len(records)} souborů do databáze")
        rows = [{"s": job.scan_id, "p": r.path, "k": r.key, "z": r.size, "m": r.mtime} for r in records]
        with db.write_tx() as conn:
            conn.execute(
                text(
                    "UPDATE scans SET status = 'done', finished_at = :now, total_files = :n, "
                    "total_size = :size, error = NULL, log = :log WHERE id = :id"
                ),
                {"now": db.now_iso(), "n": len(records), "size": sum(r.size for r in records),
                 "log": progress.log_text(), "id": job.scan_id},
            )
            for i in range(0, len(rows), INSERT_CHUNK):
                conn.execute(
                    text("INSERT INTO files (scan_id, path, key, size, mtime) VALUES (:s, :p, :k, :z, :m)"),
                    rows[i:i + INSERT_CHUNK],
                )
            # Jen poslední stav: starší skeny této strany (i s jejich soubory) pryč.
            conn.execute(
                text("DELETE FROM scans WHERE pair_id = :p AND side = :side AND id <> :id AND status NOT IN ('queued', 'running')"),
                {"p": job.pair_id, "side": job.side, "id": job.scan_id},
            )

    def _finish_failed(self, job: ActiveScan, status: str, error: str | None) -> None:
        try:
            with db.write_tx() as conn:
                conn.execute(
                    text("UPDATE scans SET status = :st, finished_at = :now, error = :err, log = :log WHERE id = :id"),
                    {"st": status, "now": db.now_iso(), "err": error, "log": job.progress.log_text(), "id": job.scan_id},
                )
                # Předchozí úspěšný sken zůstává; starší neúspěšné pokusy se uklidí.
                conn.execute(
                    text(
                        "DELETE FROM scans WHERE pair_id = :p AND side = :side AND id <> :id "
                        "AND status IN ('failed', 'cancelled')"
                    ),
                    {"p": job.pair_id, "side": job.side, "id": job.scan_id},
                )
        except Exception:
            logger.exception("Sken #%d: nepodařilo se zapsat stav %s", job.scan_id, status)


def recover_interrupted() -> int:
    """Při startu: skeny, které běžely při vypnutí aplikace, označit jako selhané."""
    return db.execute(
        "UPDATE scans SET status = 'failed', finished_at = :now, error = 'Přerušeno restartem aplikace.' "
        "WHERE status IN ('queued', 'running')",
        {"now": db.now_iso()},
    )


runner = ScanRunner()
