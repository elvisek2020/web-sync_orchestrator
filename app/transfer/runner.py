"""Přímý přenos NAS → NAS: nahrání označených souborů a smazání označených přebývajících.

Zásady:
- běží na pozadí ve vlákně; průběh je v paměti (UI se ptá každou sekundu);
- soubor se nahrává pod dočasným názvem (.jmeno.syncpart) a přejmenuje se až celý —
  na cíli nikdy nezůstane napůl nahraný soubor; přerušené nahrávání příště naváže;
- chyba jednoho souboru přenos nezastaví, výpadek spojení se zkusí znovu (navázáním);
- výsledek se promítne do posledního skenu cíle, takže čísla u páru sedí hned.
"""
from __future__ import annotations

import logging
import os
import posixpath
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass, field

from app import db
from app.config import settings
from app.core.keys import FileRec
from app.core.plan import EXTRA, Item

from .targets import LocalTarget, SftpTarget, as_str, part_name

logger = logging.getLogger("sync.transfer")

CHUNK = 256 * 1024
FILE_RETRIES = 3
SPEED_WINDOW = 5.0            # sekund pro klouzavý průměr rychlosti
MAX_FAILURES_IN_ROW = 5       # pak se přenos ukončí (nejspíš je cíl nedostupný)


class TransferCancelled(Exception):
    pass


@dataclass
class TransferProgress:
    files_total: int = 0
    bytes_total: int = 0
    delete_total: int = 0
    files_done: int = 0
    bytes_done: int = 0
    deleted: int = 0
    failed: int = 0
    current: str = ""
    current_size: int = 0
    current_done: int = 0
    phase: str = "Připojuji se…"
    started: float = field(default_factory=time.monotonic)
    cancel: threading.Event = field(default_factory=threading.Event)
    samples: deque = field(default_factory=lambda: deque(maxlen=200))
    log_lines: deque = field(default_factory=lambda: deque(maxlen=2000))
    errors: list = field(default_factory=list)

    def log(self, message: str) -> None:
        self.log_lines.append(f"{time.strftime('%H:%M:%S')} {message}")

    def check_cancel(self) -> None:
        if self.cancel.is_set():
            raise TransferCancelled("Přenos byl zrušen.")

    def add_bytes(self, n: int) -> None:
        self.bytes_done += n
        self.current_done += n
        self.samples.append((time.monotonic(), self.bytes_done))

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    @property
    def speed(self) -> float:
        """Bajty za sekundu, klouzavý průměr za posledních pár sekund."""
        now = time.monotonic()
        while self.samples and now - self.samples[0][0] > SPEED_WINDOW:
            self.samples.popleft()
        if len(self.samples) < 2:
            return 0.0
        (t0, b0), (t1, b1) = self.samples[0], self.samples[-1]
        return (b1 - b0) / (t1 - t0) if t1 > t0 else 0.0

    @property
    def eta(self) -> float | None:
        speed = self.speed
        remaining = self.bytes_total - self.bytes_done
        if speed <= 0:
            return None
        return remaining / speed

    @property
    def percent(self) -> float:
        if self.bytes_total:
            return min(self.bytes_done / self.bytes_total, 1.0) * 100
        total = self.files_total + self.delete_total
        return (self.files_done + self.deleted + self.failed) / total * 100 if total else 100.0

    @property
    def file_percent(self) -> float:
        return min(self.current_done / self.current_size, 1.0) * 100 if self.current_size else 0.0

    def log_text(self) -> str:
        return "\n".join(self.log_lines)


@dataclass
class ActiveTransfer:
    transfer_id: int
    pair_id: int
    progress: TransferProgress
    thread: threading.Thread | None = None


def split_items(items: list[Item]) -> tuple[list[Item], list[Item]]:
    uploads = [i for i in items if i.category != EXTRA and i.src is not None]
    deletions = [i for i in items if i.category == EXTRA and i.tgt is not None]
    return uploads, deletions


class TransferRunner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[int, ActiveTransfer] = {}   # podle pair_id

    def active(self, pair_id: int) -> ActiveTransfer | None:
        with self._lock:
            return self._active.get(pair_id)

    def any_running(self) -> bool:
        with self._lock:
            return bool(self._active)

    def cancel(self, pair_id: int) -> bool:
        job = self.active(pair_id)
        if job:
            job.progress.cancel.set()
            return True
        return False

    def start(self, pair: dict, items: list[Item], target_scan_id: int) -> int | None:
        """Spustí přenos pro položky páru. None = už běží."""
        from app.apps.pairs import db as pairs_db

        uploads, deletions = split_items(items)
        with self._lock:
            if pair["id"] in self._active:
                return None
            transfer_id = pairs_db.create_transfer(
                pair["id"], files_total=len(uploads), bytes_total=sum(i.src.size for i in uploads),
                delete_total=len(deletions),
            )
            progress = TransferProgress(
                files_total=len(uploads), bytes_total=sum(i.src.size for i in uploads), delete_total=len(deletions),
            )
            job = ActiveTransfer(transfer_id, pair["id"], progress)
            job.thread = threading.Thread(
                target=self._run, args=(job, pair, uploads, deletions, target_scan_id),
                daemon=True, name=f"transfer-{transfer_id}",
            )
            self._active[pair["id"]] = job
        job.thread.start()
        logger.info("Přímý přenos #%d (pár %d): %d souborů k nahrání, %d ke smazání",
                    transfer_id, pair["id"], len(uploads), len(deletions))
        return transfer_id

    # --- běh ---

    def _make_target(self, pair: dict):
        host_id = pair["target_host_id"]
        if host_id:
            host = db.query_one("SELECT * FROM hosts WHERE id = :id", {"id": host_id})
            if not host:
                raise RuntimeError("SSH host cíle neexistuje.")
            return SftpTarget(host, pair["target_path"])
        return LocalTarget(str(settings.local_root / pair["target_path"].strip("/")))

    def _run(self, job: ActiveTransfer, pair: dict, uploads: list[Item], deletions: list[Item], scan_id: int) -> None:
        from app.apps.pairs import db as pairs_db
        from app.apps.pairs.state import invalidate_scan

        progress = job.progress
        status, error = "failed", None
        added: list[FileRec] = []
        removed_keys: list[str] = []
        done_keys: list[str] = []
        target = None
        source_root = settings.local_root / pair["source_path"].strip("/")
        try:
            target = self._make_target(pair)
            target.connect()
            failures_in_row = 0

            for item in deletions:                       # nejdřív mazání — je rychlé a uvolní místo
                progress.check_cancel()
                rel = as_str(item.tgt.path)
                progress.phase, progress.current, progress.current_size, progress.current_done = "Mažu", rel, 0, 0
                try:
                    if target.size(rel) is None:
                        progress.log(f"Už neexistuje: {rel}")
                    else:
                        target.remove(rel)
                        target.remove_empty_dirs(posixpath.dirname(rel))
                        progress.log(f"Smazáno: {rel}")
                    progress.deleted += 1
                    removed_keys.append(item.key)
                    done_keys.append(item.key)
                    failures_in_row = 0
                except OSError as e:
                    progress.failed += 1
                    failures_in_row += 1
                    progress.errors.append(f"{rel}: {e}")
                    progress.log(f"CHYBA mazání {rel}: {e}")
                    if failures_in_row >= MAX_FAILURES_IN_ROW:
                        raise RuntimeError(f"{failures_in_row} chyb za sebou — přenos ukončen: {e}")

            for item in uploads:
                progress.check_cancel()
                rel = as_str(item.src.path)
                try:
                    rec = self._upload(target, source_root, item, rel, progress)
                    added.append(rec)
                    if item.tgt is not None and item.tgt.path != item.src.path:
                        # konflikt s jinak zapsaným názvem na cíli (NFC/NFD) — starou verzi odstranit
                        try:
                            target.remove(as_str(item.tgt.path))
                        except OSError:
                            pass
                    removed_keys.append(item.key)
                    done_keys.append(item.key)
                    progress.files_done += 1
                    failures_in_row = 0
                except TransferCancelled:
                    raise
                except Exception as e:  # noqa: BLE001 — chyba jednoho souboru nesmí zastavit ostatní
                    progress.failed += 1
                    failures_in_row += 1
                    progress.errors.append(f"{rel}: {e}")
                    progress.log(f"CHYBA {rel}: {e}")
                    progress.bytes_done -= progress.current_done          # nezapočítávat nedokončený soubor
                    if failures_in_row >= MAX_FAILURES_IN_ROW:
                        raise RuntimeError(f"{failures_in_row} chyb za sebou — přenos ukončen: {e}")
            status = "done"
        except TransferCancelled as e:
            status, error = "cancelled", str(e)
        except Exception as e:  # noqa: BLE001
            error = f"{e}\n\n{traceback.format_exc()}"
            progress.log(f"CHYBA: {e}")
        finally:
            if target is not None:
                try:
                    target.close()
                except Exception:
                    pass
            try:
                # co se povedlo, platí i při zrušení / chybě
                pairs_db.patch_scan(scan_id, added=added, removed_keys=removed_keys)
                pairs_db.set_direct(pair["id"], done_keys, marked=False)
                invalidate_scan(scan_id)
            except Exception:
                logger.exception("Přímý přenos #%d: nepodařilo se promítnout výsledek", job.transfer_id)
            if status == "done" and progress.failed:
                error = f"{progress.failed} položek se nepodařilo přenést:\n" + "\n".join(progress.errors[:50])
            try:
                pairs_db.finish_transfer(
                    job.transfer_id, status=status, files_done=progress.files_done, bytes_done=progress.bytes_done,
                    deleted=progress.deleted, failed=progress.failed, error=error, log=progress.log_text(),
                )
            except Exception:
                logger.exception("Přímý přenos #%d: nepodařilo se zapsat stav", job.transfer_id)
            with self._lock:
                self._active.pop(job.pair_id, None)
            logger.info("Přímý přenos #%d skončil: %s, nahráno %d, smazáno %d, chyb %d, %.0f s",
                        job.transfer_id, status, progress.files_done, progress.deleted, progress.failed,
                        progress.elapsed)

    def _upload(self, target, source_root, item: Item, rel: str, progress: TransferProgress) -> FileRec:
        local = os.path.join(source_root, rel)
        st = os.stat(local)
        size, mtime = st.st_size, st.st_mtime
        part = part_name(rel)
        progress.phase, progress.current, progress.current_size, progress.current_done = "Nahrávám", rel, size, 0
        target.makedirs(posixpath.dirname(rel))

        last_error: Exception | None = None
        for attempt in range(1, FILE_RETRIES + 1):
            progress.check_cancel()
            try:
                offset = target.size(part) or 0
                if offset > size:
                    offset = 0                                      # rozpracovaná verze je větší → znovu
                if offset:
                    progress.log(f"Navazuji {rel} od {offset} B")
                progress.bytes_done += offset - progress.current_done
                progress.current_done = offset
                progress.samples.clear()           # skok o navázaná data nemá zkreslit rychlost
                with open(local, "rb") as src, target.open_write(part, offset) as dst:
                    src.seek(offset)
                    while True:
                        progress.check_cancel()
                        chunk = src.read(CHUNK)
                        if not chunk:
                            break
                        dst.write(chunk)
                        progress.add_bytes(len(chunk))
                if target.size(part) != size:
                    raise OSError(f"velikost po nahrání nesedí ({target.size(part)} ≠ {size})")
                target.replace(part, rel)
                target.set_mtime(rel, mtime)
                progress.log(f"Nahráno: {rel}")
                return FileRec(rel.encode("utf-8", "surrogateescape"), item.key, size, mtime)
            except TransferCancelled:
                raise
            except Exception as e:  # noqa: BLE001 — výpadek spojení: znovu připojit a navázat
                last_error = e
                progress.log(f"Pokus {attempt}/{FILE_RETRIES} u {rel} selhal: {e}")
                if attempt < FILE_RETRIES:
                    time.sleep(2 * attempt)
                    try:
                        target.close()
                        target.connect()
                    except Exception as ce:  # noqa: BLE001
                        last_error = ce
        raise last_error or OSError("nahrání selhalo")


def recover_interrupted() -> int:
    from app.apps.pairs import db as pairs_db

    return pairs_db.recover_interrupted_transfers()


transfer_runner = TransferRunner()
