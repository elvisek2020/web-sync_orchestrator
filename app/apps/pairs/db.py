"""Páry, skeny, soubory a ručně vyřazené soubory — SQL."""
from __future__ import annotations

import json
import re
import threading
import unicodedata
from collections import OrderedDict

from sqlalchemy import text

from app import db
from app.core.keys import FileRec

# --- páry ---

def list_pairs() -> list[dict]:
    return db.query_all(
        "SELECT p.*, sh.name AS source_host_name, th.name AS target_host_name "
        "FROM pairs p LEFT JOIN hosts sh ON sh.id = p.source_host_id "
        "LEFT JOIN hosts th ON th.id = p.target_host_id ORDER BY p.position, p.id"
    )


def get_pair(pair_id: int) -> dict | None:
    return db.query_one(
        "SELECT p.*, sh.name AS source_host_name, th.name AS target_host_name "
        "FROM pairs p LEFT JOIN hosts sh ON sh.id = p.source_host_id "
        "LEFT JOIN hosts th ON th.id = p.target_host_id WHERE p.id = :id",
        {"id": pair_id},
    )


def slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")
    return slug or "par"


def unique_slug(name: str, pair_id: int | None = None) -> str:
    base = slugify(name)
    slug, n = base, 2
    while db.query_one(
        "SELECT id FROM pairs WHERE slug = :s AND id <> :id", {"s": slug, "id": pair_id or 0}
    ):
        slug, n = f"{base}-{n}", n + 1
    return slug


def save_pair(pair_id: int | None, data: dict) -> int:
    params = dict(data, slug=unique_slug(data["name"], pair_id))
    if pair_id:
        db.execute(
            "UPDATE pairs SET name = :name, slug = :slug, source_host_id = :source_host_id, "
            "source_path = :source_path, target_host_id = :target_host_id, target_path = :target_path "
            "WHERE id = :id",
            dict(params, id=pair_id),
        )
        return pair_id
    pos = db.query_one("SELECT COALESCE(MAX(position), 0) + 1 AS p FROM pairs")["p"]
    return db.execute(
        "INSERT INTO pairs (name, slug, position, source_host_id, source_path, target_host_id, target_path, created_at) "
        "VALUES (:name, :slug, :pos, :source_host_id, :source_path, :target_host_id, :target_path, :now)",
        dict(params, pos=pos, now=db.now_iso()),
    )


def update_pair_options(pair_id: int, *, include_conflicts: bool, include_extra: bool, exclude_patterns: str) -> None:
    db.execute(
        "UPDATE pairs SET include_conflicts = :c, include_extra = :e, exclude_patterns = :x WHERE id = :id",
        {"c": int(include_conflicts), "e": int(include_extra), "x": exclude_patterns, "id": pair_id},
    )


def set_on_disk(pair_id: int, value: bool) -> None:
    db.execute("UPDATE pairs SET on_disk = :v WHERE id = :id", {"v": int(value), "id": pair_id})


def delete_pair(pair_id: int) -> None:
    db.execute("DELETE FROM pairs WHERE id = :id", {"id": pair_id})


def move_pair(pair_id: int, direction: int) -> None:
    pairs = list_pairs()
    ids = [p["id"] for p in pairs]
    if pair_id not in ids:
        return
    i = ids.index(pair_id)
    j = i + direction
    if 0 <= j < len(ids):
        ids[i], ids[j] = ids[j], ids[i]
    db.execute_many("UPDATE pairs SET position = :pos WHERE id = :id",
                    [{"pos": n, "id": pid} for n, pid in enumerate(ids, start=1)])


# --- skeny ---

def scans_for_pair(pair_id: int) -> list[dict]:
    return db.query_all(
        "SELECT id, pair_id, side, status, created_at, started_at, finished_at, total_files, total_size, error "
        "FROM scans WHERE pair_id = :p ORDER BY id DESC",
        {"p": pair_id},
    )


def get_scan(scan_id: int) -> dict | None:
    return db.query_one("SELECT * FROM scans WHERE id = :id", {"id": scan_id})


def mark_dead_scan(scan_id: int) -> None:
    db.execute(
        "UPDATE scans SET status = 'failed', finished_at = :now, "
        "error = COALESCE(error, 'Sken přestal běžet (vlákno už neexistuje).') "
        "WHERE id = :id AND status IN ('queued', 'running')",
        {"now": db.now_iso(), "id": scan_id},
    )


# Soubory dokončeného skenu se už nemění → lze je držet v paměti (klíčem je id skenu).
_files_cache: "OrderedDict[int, list[FileRec]]" = OrderedDict()
_files_lock = threading.Lock()
_FILES_CACHE_SIZE = 12


def load_files(scan_id: int) -> list[FileRec]:
    with _files_lock:
        if scan_id in _files_cache:
            _files_cache.move_to_end(scan_id)
            return _files_cache[scan_id]
    rows = db.query_all("SELECT path, key, size, mtime FROM files WHERE scan_id = :s", {"s": scan_id})
    files = [FileRec(bytes(r["path"]), r["key"], int(r["size"]), float(r["mtime"])) for r in rows]
    with _files_lock:
        _files_cache[scan_id] = files
        while len(_files_cache) > _FILES_CACHE_SIZE:
            _files_cache.popitem(last=False)
    return files


# --- ručně vyřazené soubory ---

def skips_for_pair(pair_id: int) -> set[str]:
    return {r["key"] for r in db.query_all("SELECT key FROM pair_skips WHERE pair_id = :p", {"p": pair_id})}


def set_skips(pair_id: int, keys: list[str], skipped: bool) -> None:
    if not keys:
        return
    now = db.now_iso()
    rows = [{"p": pair_id, "k": k, "now": now} for k in keys]
    if skipped:
        with db.write_tx() as conn:  # vyřazený soubor nemůže být zároveň k přímému přenosu
            conn.execute(text("DELETE FROM pair_direct WHERE pair_id = :p AND key = :k"), rows)
            conn.execute(text("INSERT OR IGNORE INTO pair_skips (pair_id, key, created_at) VALUES (:p, :k, :now)"), rows)
    else:
        db.execute_many("DELETE FROM pair_skips WHERE pair_id = :p AND key = :k", rows)


# --- soubory označené k přímému přenosu (NAS → NAS přes SFTP) ---

def direct_for_pair(pair_id: int) -> set[str]:
    return {r["key"] for r in db.query_all("SELECT key FROM pair_direct WHERE pair_id = :p", {"p": pair_id})}


def set_direct(pair_id: int, keys: list[str], marked: bool) -> None:
    if not keys:
        return
    now = db.now_iso()
    rows = [{"p": pair_id, "k": k, "now": now} for k in keys]
    if marked:
        with db.write_tx() as conn:  # označení k přenosu ruší vyřazení
            conn.execute(text("DELETE FROM pair_skips WHERE pair_id = :p AND key = :k"), rows)
            conn.execute(text("INSERT OR IGNORE INTO pair_direct (pair_id, key, created_at) VALUES (:p, :k, :now)"), rows)
    else:
        db.execute_many("DELETE FROM pair_direct WHERE pair_id = :p AND key = :k", rows)


# --- přenosy: přímý (NAS → NAS) a na disk; drží se jen poslední záznam každého druhu pro pár ---

TRANSFER_KINDS = ("direct", "disk")


def create_transfer(pair_id: int, *, kind: str = "direct", files_total: int, bytes_total: int,
                    delete_total: int) -> int:
    with db.write_tx() as conn:
        conn.execute(text("DELETE FROM transfers WHERE pair_id = :p AND kind = :k"), {"p": pair_id, "k": kind})
        result = conn.execute(
            text(
                "INSERT INTO transfers (pair_id, kind, status, created_at, files_total, bytes_total, delete_total) "
                "VALUES (:p, :k, 'running', :now, :f, :b, :d)"
            ),
            {"p": pair_id, "k": kind, "now": db.now_iso(), "f": files_total, "b": bytes_total, "d": delete_total},
        )
        return int(result.lastrowid)


def finish_transfer(transfer_id: int, *, status: str, files_done: int, bytes_done: int, deleted: int,
                    failed: int, error: str | None, log: str, results: list | None = None) -> None:
    db.execute(
        "UPDATE transfers SET status = :st, finished_at = :now, files_done = :fd, bytes_done = :bd, "
        "deleted = :del, failed = :fail, error = :err, log = :log, results = :res WHERE id = :id",
        {"st": status, "now": db.now_iso(), "fd": files_done, "bd": bytes_done, "del": deleted,
         "fail": failed, "err": error, "log": log, "res": json.dumps(results or []), "id": transfer_id},
    )


_LAST_TRANSFER_SQL = (
    "SELECT t.* FROM transfers t WHERE t.pair_id = :p AND t.kind = :k AND NOT EXISTS ("
    " SELECT 1 FROM scans s WHERE s.pair_id = t.pair_id AND s.side = 'target' AND s.status = 'done'"
    " AND s.finished_at > COALESCE(t.finished_at, t.created_at)) "
    "ORDER BY t.id DESC LIMIT 1"
)


def last_transfer(pair_id: int, kind: str = "direct") -> dict | None:
    """Poslední přenos daného druhu — jen dokud po něm nedoběhne nový sken cíle (Aktualizovat).

    Pak už stav páru ukazuje sken a výsledek přenosu je jen historie; řádek zůstává v DB
    do dalšího přenosu stejného druhu (create_transfer ho nahradí).
    """
    row = db.query_one(_LAST_TRANSFER_SQL, {"p": pair_id, "k": kind})
    if row:
        try:
            row["items"] = json.loads(row.get("results") or "[]")
        except ValueError:
            row["items"] = []
    return row


def last_transfers(pair_id: int) -> list[dict]:
    """Poslední přenos každého druhu (nejnovější první) — karty v detailu páru."""
    rows = [t for kind in TRANSFER_KINDS if (t := last_transfer(pair_id, kind))]
    return sorted(rows, key=lambda t: t["id"], reverse=True)


def delete_transfer(pair_id: int, transfer_id: int) -> None:
    """Odebere dokončený přenos (karta v detailu páru zmizí); běžící se nemaže."""
    db.execute("DELETE FROM transfers WHERE id = :id AND pair_id = :p AND status != 'running'",
               {"id": transfer_id, "p": pair_id})


def recover_interrupted_transfers() -> int:
    return db.execute(
        "UPDATE transfers SET status = 'failed', finished_at = :now, error = 'Přerušeno restartem aplikace.' "
        "WHERE status = 'running'",
        {"now": db.now_iso()},
    )


def patch_scan(scan_id: int, *, added: list[FileRec], removed_keys: list[str]) -> None:
    """Promítne výsledek přímého přenosu do posledního skenu cíle (bez nového skenu)."""
    with db.write_tx() as conn:
        exists = conn.execute(text("SELECT 1 FROM scans WHERE id = :s AND status = 'done'"), {"s": scan_id}).first()
        if not exists:
            return
        keys = removed_keys + [r.key for r in added]
        if keys:
            conn.execute(text("DELETE FROM files WHERE scan_id = :s AND key = :k"), [{"s": scan_id, "k": k} for k in keys])
        if added:
            conn.execute(
                text("INSERT INTO files (scan_id, path, key, size, mtime) VALUES (:s, :p, :k, :z, :m)"),
                [{"s": scan_id, "p": r.path, "k": r.key, "z": r.size, "m": r.mtime} for r in added],
            )
        conn.execute(
            text(
                "UPDATE scans SET total_files = (SELECT COUNT(*) FROM files WHERE scan_id = :s), "
                "total_size = (SELECT COALESCE(SUM(size), 0) FROM files WHERE scan_id = :s) WHERE id = :s"
            ),
            {"s": scan_id},
        )
    with _files_lock:
        _files_cache.pop(scan_id, None)
