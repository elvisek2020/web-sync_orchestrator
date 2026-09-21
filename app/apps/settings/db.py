"""SSH hosté a globální nastavení — SQL.

Heslo hosta je write-only: do šablon jde vždy jen `list_hosts()` / `get_host_public()`
bez sloupce password. Plný záznam (`get_host_secret`) používá jen skener a test spojení.
"""
from __future__ import annotations

from app import db

PUBLIC_COLUMNS = "id, name, host, port, username, (password <> '') AS has_password, created_at"


def list_hosts() -> list[dict]:
    return db.query_all(f"SELECT {PUBLIC_COLUMNS} FROM hosts ORDER BY name")


def get_host_public(host_id: int) -> dict | None:
    return db.query_one(f"SELECT {PUBLIC_COLUMNS} FROM hosts WHERE id = :id", {"id": host_id})


def get_host_secret(host_id: int) -> dict | None:
    return db.query_one("SELECT * FROM hosts WHERE id = :id", {"id": host_id})


def save_host(host_id: int | None, *, name: str, host: str, port: int, username: str, password: str | None) -> int:
    """password=None → ponechat stávající heslo."""
    params = {"name": name, "host": host, "port": port, "username": username}
    if host_id:
        sql = "UPDATE hosts SET name = :name, host = :host, port = :port, username = :username"
        if password is not None:
            sql += ", password = :password"
            params["password"] = password
        db.execute(sql + " WHERE id = :id", dict(params, id=host_id))
        return host_id
    return db.execute(
        "INSERT INTO hosts (name, host, port, username, password, created_at) "
        "VALUES (:name, :host, :port, :username, :password, :now)",
        dict(params, password=password or "", now=db.now_iso()),
    )


def host_in_use(host_id: int) -> bool:
    return db.query_one(
        "SELECT id FROM pairs WHERE source_host_id = :h OR target_host_id = :h LIMIT 1", {"h": host_id}
    ) is not None


def delete_host(host_id: int) -> None:
    db.execute("DELETE FROM hosts WHERE id = :id", {"id": host_id})
