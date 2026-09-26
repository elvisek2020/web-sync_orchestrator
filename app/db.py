"""Databázová vrstva — SQLAlchemy Core nad SQLite (bez ORM)."""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Connection, Engine

from .config import settings

logger = logging.getLogger("sync.db")

_engine: Engine | None = None


def _create_engine(url: str) -> Engine:
    engine = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30}, future=True)

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn, _record):
        # Transakce řídí SQLAlchemy (event "begin" níže), ne implicitní BEGIN ovladače pysqlite.
        dbapi_conn.isolation_level = None
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    @event.listens_for(engine, "begin")
    def _on_begin(conn: Connection):
        # Zápisové transakce berou zámek hned na začátku (BEGIN IMMEDIATE),
        # jinak by přechod čtení → zápis ve WAL vracel SQLITE_BUSY bez čekání.
        mode = conn.get_execution_options().get("sqlite_begin", "DEFERRED")
        conn.exec_driver_sql(f"BEGIN {mode}")

    return engine


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        try:
            settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass  # srozumitelnou chybu nahlásí check_database()
        _engine = _create_engine(settings.db_url)
    return _engine


def reset_engine(url: str | None = None) -> None:
    """Pro testy: zahodí engine a případně nastaví jinou databázi."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = _create_engine(url) if url else None


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def query_all(sql: str, params: dict | None = None) -> list[dict[str, Any]]:
    with get_engine().connect() as conn:
        return [dict(r) for r in conn.execute(text(sql), params or {}).mappings().all()]


def query_one(sql: str, params: dict | None = None) -> dict[str, Any] | None:
    with get_engine().connect() as conn:
        row = conn.execute(text(sql), params or {}).mappings().first()
        return dict(row) if row else None


def execute(sql: str, params: dict | None = None) -> int:
    """Vrací lastrowid u INSERT, jinak počet dotčených řádků."""
    with write_tx() as conn:
        result = conn.execute(text(sql), params or {})
        return int(result.lastrowid) if result.lastrowid else result.rowcount


def execute_many(sql: str, seq_params: Iterable[dict]) -> None:
    with write_tx() as conn:
        conn.execute(text(sql), list(seq_params))


class write_tx:
    """`with write_tx() as conn:` — jedna zápisová transakce (BEGIN IMMEDIATE)."""

    def __enter__(self) -> Connection:
        self._conn = get_engine().connect().execution_options(sqlite_begin="IMMEDIATE")
        self._tx = self._conn.begin()
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self._tx.commit()
            else:
                self._tx.rollback()
        finally:
            self._conn.close()
        return False


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS settings (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS hosts (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL UNIQUE,
        host       TEXT NOT NULL,
        port       INTEGER NOT NULL DEFAULT 22,
        username   TEXT NOT NULL,
        password   TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pairs (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        name              TEXT NOT NULL UNIQUE,
        slug              TEXT NOT NULL UNIQUE,
        position          INTEGER NOT NULL DEFAULT 0,
        source_host_id    INTEGER NULL REFERENCES hosts(id) ON DELETE RESTRICT,
        source_path       TEXT NOT NULL,
        target_host_id    INTEGER NULL REFERENCES hosts(id) ON DELETE RESTRICT,
        target_path       TEXT NOT NULL,
        include_conflicts INTEGER NOT NULL DEFAULT 1,
        include_extra     INTEGER NOT NULL DEFAULT 0,
        exclude_patterns  TEXT NOT NULL DEFAULT '',
        on_disk           INTEGER NOT NULL DEFAULT 1,
        scheduled         INTEGER NOT NULL DEFAULT 0,      -- přímý přenos naplánovaný do okna
        created_at        TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scans (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        pair_id     INTEGER NOT NULL REFERENCES pairs(id) ON DELETE CASCADE,
        side        TEXT NOT NULL CHECK (side IN ('source', 'target')),
        status      TEXT NOT NULL,
        created_at  TEXT NOT NULL,
        started_at  TEXT NULL,
        finished_at TEXT NULL,
        total_files INTEGER NOT NULL DEFAULT 0,
        total_size  INTEGER NOT NULL DEFAULT 0,
        error       TEXT NULL,
        log         TEXT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_scans_pair ON scans(pair_id, side, status)",
    """
    CREATE TABLE IF NOT EXISTS files (
        scan_id INTEGER NOT NULL REFERENCES scans(id) ON DELETE CASCADE,
        path    BLOB NOT NULL,
        key     TEXT NOT NULL,
        size    INTEGER NOT NULL,
        mtime   REAL NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_files_scan ON files(scan_id)",
    "CREATE INDEX IF NOT EXISTS idx_files_scan_key ON files(scan_id, key)",
    """
    CREATE TABLE IF NOT EXISTS pair_direct (
        pair_id    INTEGER NOT NULL REFERENCES pairs(id) ON DELETE CASCADE,
        key        TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (pair_id, key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pair_ondisk (
        pair_id    INTEGER NOT NULL REFERENCES pairs(id) ON DELETE CASCADE,
        key        TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (pair_id, key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transfers (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        pair_id      INTEGER NOT NULL REFERENCES pairs(id) ON DELETE CASCADE,
        kind         TEXT NOT NULL DEFAULT 'direct',   -- direct = NAS → NAS, disk = NAS → disk
        status       TEXT NOT NULL,
        created_at   TEXT NOT NULL,
        finished_at  TEXT NULL,
        files_total  INTEGER NOT NULL DEFAULT 0,
        bytes_total  INTEGER NOT NULL DEFAULT 0,
        delete_total INTEGER NOT NULL DEFAULT 0,
        files_done   INTEGER NOT NULL DEFAULT 0,
        bytes_done   INTEGER NOT NULL DEFAULT 0,
        deleted      INTEGER NOT NULL DEFAULT 0,
        failed       INTEGER NOT NULL DEFAULT 0,
        error        TEXT NULL,
        log          TEXT NULL,
        results      TEXT NULL                          -- JSON: jak dopadl každý soubor
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS pair_skips (
        pair_id    INTEGER NOT NULL REFERENCES pairs(id) ON DELETE CASCADE,
        key        TEXT NOT NULL,
        created_at TEXT NOT NULL,
        PRIMARY KEY (pair_id, key)
    )
    """,
]


class DatabaseSetupError(RuntimeError):
    """Databázi nelze použít — zpráva je určená přímo pro člověka v logu kontejneru."""


# Tabulky, které měla jen stará verze (v1) — podle nich se pozná její databáze.
LEGACY_TABLES = {"datasets", "diffs", "batches", "batch_items", "job_runs"}


def check_database(path: Path) -> None:
    uid = os.getuid() if hasattr(os, "getuid") else "?"
    hint_new = "Nastav DATABASE_PATH na nový soubor, např. /data/sync_orchestrator.db (volume ./data:/data)."
    if not path.parent.is_dir():
        raise DatabaseSetupError(f"Adresář databáze {path.parent} neexistuje. {hint_new}")
    if not os.access(path.parent, os.W_OK) or (path.exists() and not os.access(path, os.W_OK)):
        raise DatabaseSetupError(
            f"Databáze {path} není zapisovatelná pro uživatele kontejneru (UID {uid}). "
            f"Pokud je to databáze staré verze (/mnt/usb/…), v2 ji nepoužívá — {hint_new} "
            f"Adresář musí patřit UID {uid} (chown {uid}:{uid} data), případně spusť kontejner jako root (user: \"0:0\")."
        )
    if path.exists() and path.stat().st_size > 0:
        con = sqlite3.connect(str(path))
        try:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        finally:
            con.close()
        if tables & LEGACY_TABLES:
            raise DatabaseSetupError(
                f"{path} je databáze staré verze aplikace (tabulky {', '.join(sorted(tables & LEGACY_TABLES))}). "
                f"v2 ji nepoužívá ani nemění. {hint_new}"
            )


def init_db() -> None:
    database = get_engine().url.database
    if database and database != ":memory:":
        check_database(Path(database))
    with write_tx() as conn:
        for stmt in SCHEMA_STATEMENTS:
            conn.execute(text(stmt))
        _add_missing_columns(conn)
    logger.info("Databáze připravena: %s", get_engine().url.database)


# Sloupce přidané po prvním nasazení: (tabulka, sloupec, definice).
ADDED_COLUMNS = [
    ("transfers", "kind", "TEXT NOT NULL DEFAULT 'direct'"),
    ("transfers", "results", "TEXT NULL"),
    ("pairs", "scheduled", "INTEGER NOT NULL DEFAULT 0"),
]


def _add_missing_columns(conn) -> None:
    for table, column, definition in ADDED_COLUMNS:
        existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
        if column not in existing:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
            logger.info("Databáze: přidán sloupec %s.%s", table, column)


# --- Nastavení (key/value) ---

def get_setting(key: str, default: str = "") -> str:
    row = query_one("SELECT value FROM settings WHERE key = :k", {"k": key})
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    execute(
        "INSERT INTO settings (key, value) VALUES (:k, :v) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        {"k": key, "v": value},
    )
