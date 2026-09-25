"""Přenosy na pozadí: přímý přenos NAS → NAS (nahrání označených souborů a smazání označených
přebývajících) a přenos na disk (plán páru do <disk>/<slug>/ místo kroku to-disk skriptu).

Zásady:
- běží na pozadí ve vlákně; průběh je v paměti (UI se ptá každou sekundu);
- soubor se nahrává pod dočasným názvem (.jmeno.syncpart) a přejmenuje se až celý —
  na cíli nikdy nezůstane napůl nahraný soubor; přerušené nahrávání příště naváže;
- chyba jednoho souboru přenos nezastaví, výpadek spojení se zkusí znovu (navázáním);
- soubor, který už na cíli celý je (navázání po přerušení), se přeskočí;
- přímý přenos promítne výsledek do posledního skenu cíle, takže čísla u páru sedí hned;
  přenos na disk uloží na disk i skript a po úplném dokončení manifest .sync-plan.
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
from datetime import datetime

from app import db
from app.config import settings
from app.core.keys import FileRec
from app.core.plan import EXTRA, Item

from . import disk
from .targets import LocalTarget, SftpTarget, as_str, part_name
from .window import Window

logger = logging.getLogger("sync.transfer")

CHUNK = 256 * 1024
FILE_RETRIES = 3
SPEED_WINDOW = 5.0            # sekund pro klouzavý průměr rychlosti
MAX_FAILURES_IN_ROW = 5       # pak se přenos ukončí (nejspíš je cíl nedostupný)


class TransferCancelled(Exception):
    pass


class WindowClosed(Exception):
    """Naplánovaný přenos: okno skončilo — rozpracovaný soubor se dokončil, další už nezačne."""


@dataclass
class TransferProgress:
    files_total: int = 0
    bytes_total: int = 0
    delete_total: int = 0
    files_done: int = 0
    bytes_done: int = 0
    deleted: int = 0
    failed: int = 0
    skipped: int = 0              # už byly na cíli celé (navázání)
    current: str = ""
    current_no: int = 0           # pořadí právě zpracovávané položky (1…) v aktuální fázi
    current_size: int = 0
    current_done: int = 0
    phase: str = "Připojuji se…"
    started: float = field(default_factory=time.monotonic)
    cancel: threading.Event = field(default_factory=threading.Event)
    samples: deque = field(default_factory=lambda: deque(maxlen=200))
    log_lines: deque = field(default_factory=lambda: deque(maxlen=2000))
    errors: list = field(default_factory=list)
    results: list = field(default_factory=list)   # po souborech: [čas ISO, cesta, stav, podrobnost]

    def log(self, message: str) -> None:
        now = datetime.now()
        self.log_lines.append(f"{now.day}. {now.month}. {now:%H:%M:%S} {message}")

    def result(self, path: str, status: str, detail: str = "") -> None:
        """Jak dopadl soubor: ok | skipped (už na cíli) | deleted | gone (už neexistoval) | error."""
        self.results.append([datetime.now().isoformat(timespec="seconds"), path, status, detail])

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


KIND_LABELS = {"direct": "Přímý přenos", "disk": "Přenos na disk"}


@dataclass
class ActiveTransfer:
    transfer_id: int
    pair_id: int
    progress: TransferProgress
    kind: str = "direct"                     # direct = NAS → NAS, disk = NAS → přenosový disk
    dest: str = ""                           # kam se kopíruje (zobrazí se v panelu)
    window: Window | None = None             # naplánovaný přenos: běží jen v tomto okně
    thread: threading.Thread | None = None

    @property
    def scheduled(self) -> bool:
        return self.window is not None

    def window_end(self) -> datetime | None:
        return self.window.end_after(datetime.now()) if self.window else None

    @property
    def label(self) -> str:
        return KIND_LABELS.get(self.kind, "Přenos")


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

    def disk_running(self) -> ActiveTransfer | None:
        """Přenos na disk, který právě běží (u kteréhokoli páru)."""
        with self._lock:
            return next((j for j in self._active.values() if j.kind == "disk"), None)

    def cancel(self, pair_id: int) -> bool:
        job = self.active(pair_id)
        if job:
            job.progress.cancel.set()
            return True
        return False

    def direct_running(self) -> bool:
        with self._lock:
            return any(j.kind == "direct" for j in self._active.values())

    def start(self, pair: dict, items: list[Item], target_scan_id: int, window: Window | None = None) -> int | None:
        """Přímý přenos NAS → NAS pro označené položky. S oknem = naplánovaný: po konci okna
        další soubor nezačne a přenos skončí jako „pozastavený“. None = u páru už něco běží."""
        from app.apps.pairs import db as pairs_db
        from app.apps.pairs.state import invalidate_scan

        uploads, deletions = split_items(items)

        def finish(job: ActiveTransfer, status: str, added: list[FileRec], removed_keys: list[str],
                   done_keys: list[str]) -> None:
            # co se povedlo, platí i při zrušení / chybě
            pairs_db.patch_scan(target_scan_id, added=added, removed_keys=removed_keys)
            pairs_db.set_direct(pair["id"], done_keys, marked=False)
            invalidate_scan(target_scan_id)
            if job.scheduled and status in ("done", "cancelled"):
                pairs_db.set_scheduled(pair["id"], False)     # vše prošlo (nebo zrušeno) → plán hotový

        return self._launch(pair, "direct", uploads, deletions, dest="NAS2", window=window,
                            make_target=lambda: self._make_target(pair), prepare=None, finish=finish)

    def start_disk(self, pair: dict, items: list[Item], *, script_name: str, script_text: str,
                   plan_hash: str) -> int | None:
        """Přenos na disk: soubory do <disk>/<slug>/, skript do kořene disku, po úplném dokončení
        manifest .sync-plan (krok to-nas skriptu ho kontroluje). None = u páru už něco běží,
        nebo se na disk právě kopíruje jiný pár."""
        uploads = [i for i in items if i.src is not None]
        root = disk.pair_dir(pair)
        manifest = root / disk.MANIFEST

        def prepare(job: ActiveTransfer) -> None:
            root.mkdir(parents=True, exist_ok=True)
            script = settings.disk_path / script_name
            script.write_text(script_text, encoding="utf-8")
            job.progress.log(f"Skript uložen: {script}")
            # manifest platí až po úplném přenosu — do té doby to-nas upozorní, že to-disk nedoběhl
            manifest.unlink(missing_ok=True)

        def finish(job: ActiveTransfer, status: str, added: list[FileRec], removed_keys: list[str],
                   done_keys: list[str]) -> None:
            if status == "done" and not job.progress.failed:
                manifest.write_text(f"PLAN={plan_hash}\nCREATED={time.strftime('%Y-%m-%d %H:%M:%S')}\n",
                                    encoding="utf-8")
                job.progress.log(f"Manifest {disk.MANIFEST} zapsán (plán {plan_hash}) — disk je připravený pro to-nas.")

        return self._launch(pair, "disk", uploads, [], dest=str(root),
                            make_target=lambda: LocalTarget(str(root)), prepare=prepare, finish=finish)

    def _launch(self, pair: dict, kind: str, uploads: list[Item], deletions: list[Item], *, dest: str,
                make_target, prepare, finish, window: Window | None = None) -> int | None:
        from app.apps.pairs import db as pairs_db

        bytes_total = sum(i.src.size for i in uploads)
        with self._lock:
            if pair["id"] in self._active:
                return None
            if kind == "disk" and any(j.kind == "disk" for j in self._active.values()):
                return None                          # na disk vždy jen jeden přenos
            transfer_id = pairs_db.create_transfer(
                pair["id"], kind=kind, files_total=len(uploads), bytes_total=bytes_total,
                delete_total=len(deletions),
            )
            progress = TransferProgress(files_total=len(uploads), bytes_total=bytes_total,
                                        delete_total=len(deletions))
            job = ActiveTransfer(transfer_id, pair["id"], progress, kind=kind, dest=dest, window=window)
            job.thread = threading.Thread(
                target=self._run, args=(job, pair, uploads, deletions, make_target, prepare, finish),
                daemon=True, name=f"transfer-{transfer_id}",
            )
            self._active[pair["id"]] = job
        job.thread.start()
        logger.info("%s #%d (pár %d): %d souborů, %d ke smazání",
                    job.label, transfer_id, pair["id"], len(uploads), len(deletions))
        return transfer_id

    # --- běh ---

    @staticmethod
    def _check_window(job: ActiveTransfer) -> None:
        if job.window and not job.window.contains(datetime.now()):
            raise WindowClosed()

    def _make_target(self, pair: dict):
        host_id = pair["target_host_id"]
        if host_id:
            host = db.query_one("SELECT * FROM hosts WHERE id = :id", {"id": host_id})
            if not host:
                raise RuntimeError("SSH host cíle neexistuje.")
            return SftpTarget(host, pair["target_path"])
        return LocalTarget(str(settings.local_root / pair["target_path"].strip("/")))

    def _run(self, job: ActiveTransfer, pair: dict, uploads: list[Item], deletions: list[Item],
             make_target, prepare, finish) -> None:
        from app.apps.pairs import db as pairs_db

        progress = job.progress
        status, error = "failed", None
        added: list[FileRec] = []
        removed_keys: list[str] = []
        done_keys: list[str] = []
        target = None
        source_root = settings.local_root / pair["source_path"].strip("/")
        try:
            if prepare:
                prepare(job)
            target = make_target()
            target.connect()
            failures_in_row = 0

            for no, item in enumerate(deletions, 1):     # nejdřív mazání — je rychlé a uvolní místo
                progress.check_cancel()
                self._check_window(job)
                progress.current_no = no
                rel = as_str(item.tgt.path)
                progress.phase, progress.current, progress.current_size, progress.current_done = "Mažu", rel, 0, 0
                try:
                    if target.size(rel) is None:
                        progress.result(rel, "gone")
                    else:
                        target.remove(rel)
                        target.remove_empty_dirs(posixpath.dirname(rel))
                        progress.result(rel, "deleted")
                    progress.deleted += 1
                    removed_keys.append(item.key)
                    done_keys.append(item.key)
                    failures_in_row = 0
                except OSError as e:
                    progress.failed += 1
                    failures_in_row += 1
                    progress.errors.append(f"{rel}: {e}")
                    progress.result(rel, "error", f"mazání: {e}")
                    if failures_in_row >= MAX_FAILURES_IN_ROW:
                        raise RuntimeError(f"{failures_in_row} chyb za sebou — přenos ukončen: {e}")

            for no, item in enumerate(uploads, 1):
                progress.check_cancel()
                self._check_window(job)
                progress.current_no = no
                rel = as_str(item.src.path)
                try:
                    rec = self._upload(job, target, source_root, item, rel)
                    added.append(rec)
                    if job.kind == "direct" and item.tgt is not None and item.tgt.path != item.src.path:
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
                    progress.result(rel, "error", str(e))
                    progress.bytes_done -= progress.current_done          # nezapočítávat nedokončený soubor
                    if failures_in_row >= MAX_FAILURES_IN_ROW:
                        raise RuntimeError(f"{failures_in_row} chyb za sebou — přenos ukončen: {e}")
            status = "done"
        except TransferCancelled as e:
            status, error = "cancelled", str(e)
        except WindowClosed:
            status = "paused"
            progress.log(f"Okno {job.window.label} skončilo — zbytek pokračuje v dalším okně.")
        except Exception as e:  # noqa: BLE001
            error = f"{e}\n\n{traceback.format_exc()}"
            progress.log(f"CHYBA: {e}")
        finally:
            if target is not None:
                try:
                    target.close()
                except Exception:
                    pass
            if progress.skipped:
                progress.log(f"Už bylo na cíli (přeskočeno): {progress.skipped}")
            try:
                finish(job, status, added, removed_keys, done_keys)
            except Exception as e:  # noqa: BLE001
                logger.exception("%s #%d: nepodařilo se dokončit", job.label, job.transfer_id)
                progress.log(f"CHYBA při dokončení: {e}")
                if status == "done":
                    status, error = "failed", f"Přenos doběhl, ale nepodařilo se ho dokončit: {e}"
            if status == "done" and progress.failed:
                error = f"{progress.failed} položek se nepodařilo přenést:\n" + "\n".join(progress.errors[:50])
            try:
                pairs_db.finish_transfer(
                    job.transfer_id, status=status, files_done=progress.files_done, bytes_done=progress.bytes_done,
                    deleted=progress.deleted, failed=progress.failed, error=error, log=progress.log_text(),
                    results=progress.results,
                )
            except Exception:
                logger.exception("%s #%d: nepodařilo se zapsat stav", job.label, job.transfer_id)
            with self._lock:
                self._active.pop(job.pair_id, None)
            logger.info("%s #%d skončil: %s, přeneseno %d, smazáno %d, chyb %d, %.0f s",
                        job.label, job.transfer_id, status, progress.files_done, progress.deleted, progress.failed,
                        progress.elapsed)

    def _upload(self, job: ActiveTransfer, target, source_root, item: Item, rel: str) -> FileRec:
        progress = job.progress
        local = os.path.join(source_root, rel)
        st = os.stat(local)
        size, mtime = st.st_size, st.st_mtime
        part = part_name(rel)
        phase = "Kopíruji" if job.kind == "disk" else "Nahrávám"
        progress.phase, progress.current, progress.current_size, progress.current_done = phase, rel, size, 0
        if target.size(rel) == size:
            # už je na cíli celý (navázání po přerušení) — nekopírovat znovu
            progress.skipped += 1
            progress.result(rel, "skipped")
            progress.bytes_done += size
            progress.samples.clear()                   # skok o přeskočená data nemá zkreslit rychlost
            return FileRec(rel.encode("utf-8", "surrogateescape"), item.key, size, mtime)
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
                    target.finish_write(dst)
                if target.size(part) != size:
                    raise OSError(f"velikost po nahrání nesedí ({target.size(part)} ≠ {size})")
                target.replace(part, rel)
                target.set_mtime(rel, mtime)
                progress.result(rel, "ok")
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
