"""Společné fixtures: dočasná databáze a dočasný „NAS1“ kořen."""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from app import db
from app.apps.pairs import db as pairs_db
from app.config import settings
from app.core.keys import FileRec, key_from_local


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    local_root = tmp_path / "nas1"
    local_root.mkdir()
    monkeypatch.setattr(settings, "database_path", db_path)
    monkeypatch.setattr(settings, "local_root", local_root)
    db.reset_engine(f"sqlite:///{db_path}")
    pairs_db._files_cache.clear()
    db.init_db()
    yield local_root
    db.reset_engine(None)


def write_file(root: Path, rel: str, content: bytes = b"x") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def rec(rel: str, size: int = 1) -> FileRec:
    return FileRec(rel.encode("utf-8"), key_from_local(rel), size, 0.0)


def wait_for_scans(timeout: float = 20.0) -> None:
    from app.scan.runner import runner

    deadline = time.monotonic() + timeout
    while runner.any_running():
        if time.monotonic() > deadline:
            raise TimeoutError("Skeny nedoběhly.")
        time.sleep(0.05)
