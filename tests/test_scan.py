"""Lokální sken a běh skenů na pozadí (s dočasnou databází)."""
from __future__ import annotations

import os
import unicodedata

import pytest

from app import db
from app.apps.pairs import db as pairs_db
from app.apps.pairs.state import load_overview
from app.core.excludes import DEFAULT_EXCLUDE_PATTERNS, Excluder
from app.scan.common import Progress, ScanError
from app.scan.local import scan_local
from app.scan.runner import recover_interrupted, runner

from .conftest import wait_for_scans, write_file

running_as_root = hasattr(os, "geteuid") and os.geteuid() == 0


def test_local_scan_basic(tmp_path):
    write_file(tmp_path, "Filmy/A (2001)/A.mkv", b"12345")
    write_file(tmp_path, "Filmy/@eaDir/thumb.jpg")
    write_file(tmp_path, unicodedata.normalize("NFD", "Pohádky/Příběh.avi"))
    os.symlink(tmp_path / "Filmy", tmp_path / "odkaz")
    recs = scan_local(tmp_path, Excluder(DEFAULT_EXCLUDE_PATTERNS), Progress(), allow_empty=False)
    keys = sorted(r.key for r in recs)
    assert keys == ["Filmy/A (2001)/A.mkv", "Pohádky/Příběh.avi"]
    nfd = next(r for r in recs if r.key.startswith("Poh"))
    assert nfd.path == unicodedata.normalize("NFD", "Pohádky/Příběh.avi").encode()  # skutečná cesta zůstává
    assert next(r for r in recs if r.key.endswith("A.mkv")).size == 5


def test_local_scan_missing_or_empty_root(tmp_path):
    with pytest.raises(ScanError):
        scan_local(tmp_path / "neni", Excluder([]), Progress(), allow_empty=True)
    (tmp_path / "prazdna").mkdir()
    with pytest.raises(ScanError, match="žádný soubor"):
        scan_local(tmp_path / "prazdna", Excluder([]), Progress(), allow_empty=False)
    assert scan_local(tmp_path / "prazdna", Excluder([]), Progress(), allow_empty=True) == []


@pytest.mark.skipif(running_as_root, reason="root přečte i složku s právy 000")
def test_local_scan_unreadable_dir_fails(tmp_path):
    write_file(tmp_path, "ok/a.txt")
    bad = tmp_path / "zamceno"
    write_file(bad, "b.txt")
    bad.chmod(0)
    try:
        with pytest.raises(ScanError, match="Nelze přečíst"):
            scan_local(tmp_path, Excluder([]), Progress(), allow_empty=False)
    finally:
        bad.chmod(0o755)


def _make_pair(local_root, name="Filmy"):
    (local_root / "src").mkdir(exist_ok=True)
    (local_root / "tgt").mkdir(exist_ok=True)
    return pairs_db.save_pair(None, {
        "name": name, "source_host_id": None, "source_path": "src",
        "target_host_id": None, "target_path": "tgt",
    })


def test_runner_success_replaces_previous_scan(temp_db):
    root = temp_db
    pid = _make_pair(root)
    write_file(root, "src/a.mkv", b"aaa")
    write_file(root, "src/b.mkv", b"bb")
    write_file(root, "tgt/b.mkv", b"bb")
    write_file(root, "tgt/old.mkv", b"o")

    runner.start_pair(pid)
    wait_for_scans()
    st = load_overview().get(pid)
    assert st.source.current["total_files"] == 2
    assert [i.key for i in st.plan.selected] == ["a.mkv"]
    assert [i.key for i in st.plan.comparison.extra] == ["old.mkv"]
    first_ids = {st.source.current["id"], st.target.current["id"]}

    write_file(root, "tgt/a.mkv", b"aaa")
    runner.start_pair(pid)
    wait_for_scans()
    scans = pairs_db.scans_for_pair(pid)
    assert len(scans) == 2 and all(s["status"] == "done" for s in scans)
    assert not first_ids & {s["id"] for s in scans}  # jen poslední stav
    assert db.query_one("SELECT COUNT(*) AS n FROM files")["n"] == 2 + 3
    assert load_overview().get(pid).plan.selected == []


def test_runner_failure_keeps_previous_scan(temp_db):
    root = temp_db
    pid = _make_pair(root)
    write_file(root, "src/a.mkv")
    runner.start_pair(pid)
    wait_for_scans()
    good = load_overview().get(pid).source.current["id"]

    # zdroj „odpojen“ → prázdná složka → sken zdroje musí selhat, ne smazat vše na cíli
    os.remove(root / "src/a.mkv")
    runner.start(pid, "source")
    wait_for_scans()
    st = load_overview().get(pid)
    assert st.source.current["id"] == good
    assert st.source.failed and "žádný soubor" in st.source.failed["error"]
    assert any("nepovedl" in w for w in st.warnings)


def test_second_start_is_refused_while_running(temp_db):
    root = temp_db
    pid = _make_pair(root)
    for i in range(200):
        write_file(root, f"src/d{i % 20}/f{i}.bin")
    first = runner.start(pid, "source")
    second = runner.start(pid, "source")
    wait_for_scans()
    assert first and second is None


def test_cancel(temp_db):
    root = temp_db
    pid = _make_pair(root)
    write_file(root, "src/a")
    sid = runner.start(pid, "source")
    runner.cancel(sid)
    wait_for_scans()
    assert pairs_db.get_scan(sid)["status"] in ("cancelled", "done")


def test_recover_interrupted_and_cascade(temp_db):
    root = temp_db
    pid = _make_pair(root)
    sid = db.execute(
        "INSERT INTO scans (pair_id, side, status, created_at) VALUES (:p, 'source', 'running', :now)",
        {"p": pid, "now": db.now_iso()},
    )
    db.execute("INSERT INTO files (scan_id, path, key, size, mtime) VALUES (:s, x'61', 'a', 1, 0)", {"s": sid})
    assert recover_interrupted() == 1
    assert pairs_db.get_scan(sid)["status"] == "failed"
    pairs_db.delete_pair(pid)
    assert db.query_one("SELECT COUNT(*) AS n FROM files")["n"] == 0


def test_dead_running_scan_is_marked_failed_on_read(temp_db):
    root = temp_db
    pid = _make_pair(root)
    sid = db.execute(
        "INSERT INTO scans (pair_id, side, status, created_at) VALUES (:p, 'target', 'running', :now)",
        {"p": pid, "now": db.now_iso()},
    )
    st = load_overview().get(pid)
    assert st.target.running is None and st.target.failed["id"] == sid
    assert pairs_db.get_scan(sid)["status"] == "failed"


def test_legacy_database_is_refused_and_left_untouched(tmp_path):
    import sqlite3

    from app.db import DatabaseSetupError, check_database

    old = tmp_path / "sync_orchestrator.db"
    con = sqlite3.connect(old)
    con.execute("CREATE TABLE datasets (id INTEGER PRIMARY KEY)")
    con.execute("CREATE TABLE scans (id INTEGER PRIMARY KEY, dataset_id INTEGER)")
    con.commit()
    con.close()
    with pytest.raises(DatabaseSetupError, match="staré verze"):
        check_database(old)
    con = sqlite3.connect(old)
    assert {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")} == {"datasets", "scans"}
    con.close()


@pytest.mark.skipif(running_as_root, reason="root zapíše i do adresáře s právy 555")
def test_readonly_database_dir_gives_clear_error(tmp_path):
    from app.db import DatabaseSetupError, check_database

    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(0o555)
    try:
        with pytest.raises(DatabaseSetupError, match="není zapisovatelná"):
            check_database(ro / "sync_orchestrator.db")
    finally:
        ro.chmod(0o755)
