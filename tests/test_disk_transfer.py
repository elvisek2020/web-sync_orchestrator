"""Přenos na disk z aplikace (místo kroku to-disk skriptu) a navazující to-nas skriptem z disku."""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app import db
from app.apps.pairs import db as pairs_db
from app.apps.pairs.state import load_overview
from app.config import settings
from app.core.script import generate_script, script_filename
from app.main import app
from app.scan.runner import runner
from app.transfer import disk
from app.transfer import runner as transfer_module
from app.transfer.runner import ActiveTransfer, TransferProgress, transfer_runner

from .conftest import wait_for_scans, write_file
from .test_transfer import wait_for_transfer


@pytest.fixture()
def disk_root(temp_db, tmp_path, monkeypatch):
    root = tmp_path / "disk"
    root.mkdir()
    monkeypatch.setattr(settings, "disk_path", root)
    monkeypatch.setattr(disk, "DISK_MIN_PLAUSIBLE", 0)       # dočasná složka není „skutečný“ disk
    monkeypatch.setattr(disk, "_same_device_as_nas", lambda path: False)   # v testu je všechno na jednom svazku
    return root


def _pair(root, name="Serialy") -> dict:
    (root / "src").mkdir(exist_ok=True)
    (root / "tgt").mkdir(exist_ok=True)
    pid = pairs_db.save_pair(None, {"name": name, "source_host_id": None, "source_path": "src",
                                    "target_host_id": None, "target_path": "tgt"})
    runner.start_pair(pid)
    wait_for_scans()
    return load_overview().get(pid)


def _start(st) -> int | None:
    script = generate_script(pair_name=st.pair["name"], slug=st.pair["slug"], plan=st.plan,
                             source_desc="NAS1", target_desc="NAS2")
    return transfer_runner.start_disk(st.pair, st.plan.selected, script_name=script_filename(st.pair["slug"]),
                                      script_text=script, plan_hash=st.plan.plan_hash())


def test_copies_plan_script_and_manifest_then_to_nas_works(temp_db, disk_root):
    root = temp_db
    write_file(root, "src/Seriál (2019)/Season 01/S01E01.mkv", b"prvni dil")
    os.utime(root / "src/Seriál (2019)/Season 01/S01E01.mkv", (1_600_000_000, 1_600_000_000))
    write_file(root, "src/Film.mkv", b"film")
    write_file(root, "tgt/stary.mkv", b"x")
    st = _pair(root)
    slug = st.pair["slug"]

    assert _start(st)
    wait_for_transfer()

    pair_dir = disk_root / slug
    assert (pair_dir / "Seriál (2019)/Season 01/S01E01.mkv").read_bytes() == b"prvni dil"
    assert os.stat(pair_dir / "Seriál (2019)/Season 01/S01E01.mkv").st_mtime == 1_600_000_000
    assert (pair_dir / "Film.mkv").read_bytes() == b"film"
    assert not list(pair_dir.rglob("*.syncpart"))
    assert (disk_root / script_filename(slug)).exists()                       # skript pro to-nas na disku
    assert (pair_dir / ".sync-plan").read_text().startswith(f"PLAN={st.plan.plan_hash()}\n")
    t = pairs_db.last_transfer(st.pair["id"], "disk")
    assert t["status"] == "done" and t["files_done"] == 2 and t["failed"] == 0
    assert pairs_db.last_transfer(st.pair["id"], "direct") is None
    # NAS2 se nezměnil — soubory dál čekají na to-nas
    assert len(load_overview().get(st.pair["id"]).plan.selected) == 2

    if shutil.which("bash") is None or shutil.which("rsync") is None:
        pytest.skip("chybí bash nebo rsync")
    r = subprocess.run(["bash", str(disk_root / script_filename(slug)), "to-nas", str(disk_root), str(root / "tgt"),
                        "--yes"], capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL,
                       timeout=60, start_new_session=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "VAROVÁNÍ" not in r.stdout                                         # plán na disku sedí se skriptem
    assert (root / "tgt/Seriál (2019)/Season 01/S01E01.mkv").read_bytes() == b"prvni dil"


def test_resume_skips_complete_files_and_manifest_only_after_success(temp_db, disk_root, monkeypatch):
    monkeypatch.setattr(transfer_module, "CHUNK", 4096)
    root = temp_db
    big = os.urandom(6 * 1024 * 1024)
    write_file(root, "src/a.mkv", b"hotovy")
    write_file(root, "src/b.bin", big)
    st = _pair(root)
    pair_dir = disk_root / st.pair["slug"]
    write_file(pair_dir, ".sync-plan", b"PLAN=stary\n")                       # manifest minulého kola

    assert _start(st)
    transfer_runner.cancel(st.pair["id"])
    wait_for_transfer()
    t = pairs_db.last_transfer(st.pair["id"], "disk")
    assert t["status"] == "cancelled"
    assert not (pair_dir / ".sync-plan").exists()                              # nedokončené kolo nemá manifest

    # a.mkv už na disku celý, b.bin napůl → a se přeskočí, b naváže
    write_file(pair_dir, "a.mkv", b"hotovy")
    write_file(pair_dir, ".b.bin.syncpart", big[: 2 * 1024 * 1024])
    (pair_dir / "b.bin").unlink(missing_ok=True)
    assert _start(load_overview().get(st.pair["id"]))
    wait_for_transfer()
    t = pairs_db.last_transfer(st.pair["id"], "disk")
    assert t["status"] == "done" and t["files_done"] == 2
    assert "Už bylo na cíli (přeskočeno): 1" in t["log"] and "Navazuji b.bin" in t["log"]
    assert [(path, status) for _, path, status, _ in t["items"]] == [("a.mkv", "skipped"), ("b.bin", "ok")]
    assert (pair_dir / "b.bin").read_bytes() == big
    assert (pair_dir / ".sync-plan").read_text().startswith(f"PLAN={st.plan.plan_hash()}")


def test_only_one_disk_transfer_at_a_time(temp_db, disk_root):
    root = temp_db
    write_file(root, "src/a.mkv", b"a")
    st = _pair(root)
    transfer_runner._active[999] = ActiveTransfer(1, 999, TransferProgress(), kind="disk")   # jiný pár kopíruje
    try:
        assert _start(st) is None
        with TestClient(app) as client:
            r = client.post(f"/pary/{st.pair['id']}/prenos-na-disk", follow_redirects=False)
            assert "disk_busy" in r.headers["location"]
    finally:
        transfer_runner._active.pop(999, None)


def test_web_flow_and_disk_checks(temp_db, disk_root, monkeypatch):
    root = temp_db
    write_file(root, "src/a.mkv", b"aaa")
    (root / "tgt").mkdir()
    with TestClient(app) as client:
        client.post("/nastaveni/pary", data={"name": "P", "source_host_id": "", "source_path": "src",
                                             "target_host_id": "", "target_path": "tgt"})
        client.post("/pary/1/aktualizovat", data={"next": "/"})
        wait_for_scans()
        page = client.get("/pary/1").text
        assert "Přenos na disk" in page and "Spustit přenos na disk?" in page
        assert 'class="btn btn-outline" download' in page                     # skript je teď vedlejší cesta

        def start():
            return client.post("/pary/1/prenos-na-disk", follow_redirects=False).headers["location"]

        real_access, real_needed = os.access, disk.bytes_needed
        monkeypatch.setattr(disk.os, "access", lambda *a, **k: False)          # připojeno :ro
        assert "disk_readonly" in start()
        monkeypatch.setattr(disk.os, "access", real_access)
        monkeypatch.setattr(disk, "DISK_MIN_PLAUSIBLE", 10**18)                  # prázdná složka místo disku
        assert "disk_suspicious" in start()
        monkeypatch.setattr(disk, "DISK_MIN_PLAUSIBLE", 0)
        monkeypatch.setattr(disk, "bytes_needed", lambda items, r: 10**18)
        assert "disk_full" in start()
        monkeypatch.setattr(disk, "bytes_needed", real_needed)

        assert "disk_started" in start()
        wait_for_transfer()
        assert (disk_root / "p/a.mkv").read_bytes() == b"aaa"
        page = client.get("/pary/1").text
        assert "Poslední přenos na disk" in page and "Disk je připravený" in page and "sync_p.sh" in page

        # bez připojeného disku tlačítko není a skript je zase hlavní cesta
        monkeypatch.setattr(settings, "disk_path", root / "neni")
        page = client.get("/pary/1").text
        assert "Spustit přenos na disk?" not in page and 'class="btn btn-primary" download' in page
        assert "disk_not_mounted" in start()


def test_transfers_kind_column_is_added_to_old_database(temp_db):
    with db.write_tx() as conn:
        conn.execute(text("DROP TABLE transfers"))
        conn.execute(text(
            "CREATE TABLE transfers (id INTEGER PRIMARY KEY AUTOINCREMENT, pair_id INTEGER NOT NULL, "
            "status TEXT NOT NULL, created_at TEXT NOT NULL, finished_at TEXT NULL, files_total INTEGER NOT NULL DEFAULT 0, "
            "bytes_total INTEGER NOT NULL DEFAULT 0, delete_total INTEGER NOT NULL DEFAULT 0, "
            "files_done INTEGER NOT NULL DEFAULT 0, bytes_done INTEGER NOT NULL DEFAULT 0, "
            "deleted INTEGER NOT NULL DEFAULT 0, failed INTEGER NOT NULL DEFAULT 0, error TEXT NULL, log TEXT NULL)"
        ))
        conn.execute(text("INSERT INTO transfers (pair_id, status, created_at) VALUES (1, 'done', '2026-09-20T10:00:00')"))
    db.init_db()
    rows = db.query_all("SELECT kind, results FROM transfers")
    assert [(r["kind"], r["results"]) for r in rows] == [("direct", None)]   # staré přenosy byly přímé
    assert pairs_db.last_transfer(1)["items"] == []                          # starý záznam bez výsledků


def test_running_disk_transfer_is_shown(temp_db, disk_root):
    root = temp_db
    write_file(root, "src/a.mkv", b"a")
    st = _pair(root)
    pid = st.pair["id"]
    progress = TransferProgress(files_total=2, bytes_total=1000, files_done=1, bytes_done=500,
                                current="Seriál/díl 2.mkv", current_no=2, current_size=500, phase="Kopíruji")
    transfer_runner._active[pid] = ActiveTransfer(1, pid, progress, kind="disk", dest="/mnt/disk/serialy")
    try:
        with TestClient(app) as client:
            assert "Přenos na disk · 50 %" in client.get("/").text
            detail = client.get(f"/pary/{pid}").text
            assert "Kopíruji na disk · /mnt/disk/serialy" in detail and "Zrušit přenos" in detail
            assert "Spustit přenos na disk?" not in detail                     # během přenosu jen zrušení
            r = client.post(f"/pary/{pid}/prenos/zrusit", follow_redirects=False)
            assert "transfer_cancelled" in r.headers["location"] and progress.cancel.is_set()
    finally:
        transfer_runner._active.pop(pid, None)


def test_clean_disk_removes_everything(temp_db, disk_root, monkeypatch):
    root = temp_db
    write_file(root, "src/a.mkv", b"a")
    st = _pair(root)                                                            # slug „serialy“
    write_file(disk_root, "serialy/Seriál/díl 1.mkv", b"x" * 100)
    write_file(disk_root, "serialy/.sync-plan", b"PLAN=x\n")
    write_file(disk_root, "sync_serialy.sh", b"#!/bin/bash\n")
    write_file(disk_root, "stary-par/film.mkv", b"y" * 50)                      # pár, který už v aplikaci není
    write_file(disk_root, "sync_stary-par.sh", b"#!/bin/bash\n")
    write_file(disk_root, "Moje fotky/dovolena.jpg", b"z")                     # smaže se i cizí obsah
    write_file(disk_root, "poznamky.txt", b"z")
    write_file(disk_root, ".skryta/x", b"z")

    with TestClient(app) as client:
        page = client.get("/nastaveni").text
        assert "Obsah disku" in page and "Vyčistit disk" in page and "Pozor, mažu!" in page
        assert "Z disku se smaže úplně všechno." in page and "8 souborů" in page

        monkeypatch.setattr(disk, "_same_device_as_nas", lambda path: True)   # špatně nastavená cesta
        r = client.post("/nastaveni/disk/vycistit", follow_redirects=False)
        assert "disk_same_as_nas" in r.headers["location"] and (disk_root / "serialy").exists()
        monkeypatch.setattr(disk, "_same_device_as_nas", lambda path: False)

        transfer_runner._active[999] = ActiveTransfer(1, 999, TransferProgress(), kind="disk")
        try:
            r = client.post("/nastaveni/disk/vycistit", follow_redirects=False)
            assert "disk_clean_busy" in r.headers["location"] and (disk_root / "serialy").exists()
        finally:
            transfer_runner._active.pop(999, None)

        page = client.get("/nastaveni").text
        assert 'data-confirm-alt="Jen smazat"' in page and "vycistit?aktualizovat=1" in page
        r = client.post("/nastaveni/disk/vycistit", follow_redirects=False)
        assert "disk_cleaned" in r.headers["location"] and "/nastaveni" in r.headers["location"]
        assert list(disk_root.iterdir()) == []                                 # disk je prázdný

        # „Smazat a aktualizovat“: přeskenuje jen páry, které mají něco k přenosu, a vrátí na Přehled
        write_file(root, "src2/film.mkv", b"f")
        write_file(root, "tgt2/film.mkv", b"f")                                 # pár bez rozdílů
        other = pairs_db.save_pair(None, {"name": "Filmy", "source_host_id": None, "source_path": "src2",
                                          "target_host_id": None, "target_path": "tgt2"})
        runner.start_pair(other)
        wait_for_scans()
        started = []
        monkeypatch.setattr(runner, "start_pair", lambda pid: started.append(pid) or [])
        write_file(disk_root, "serialy/dil.mkv", b"x")
        assert 'data-confirm-alt="Jen smazat"' in client.get("/nastaveni").text
        r = client.post("/nastaveni/disk/vycistit?aktualizovat=1", follow_redirects=False)
        assert r.headers["location"].startswith("/?") and "disk_cleaned_refresh" in r.headers["location"]
        assert started == [st.pair["id"]] and not (disk_root / "serialy").exists()   # Filmy (0 k přenosu) ne
        assert "Prázdný — disk je připravený." in client.get("/nastaveni").text
        r = client.post("/nastaveni/disk/vycistit", follow_redirects=False)
        assert "disk_clean_empty" in r.headers["location"]
