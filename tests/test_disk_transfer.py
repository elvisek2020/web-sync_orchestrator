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
    def make_script(plan):
        return generate_script(pair_name=st.pair["name"], slug=st.pair["slug"], plan=plan,
                               source_desc="NAS1", target_desc="NAS2")
    return transfer_runner.start_disk(st.pair, st.plan, script_name=script_filename(st.pair["slug"]),
                                      make_script=make_script)


def _to_nas(disk_root, slug, target):
    if shutil.which("bash") is None or shutil.which("rsync") is None:
        pytest.skip("chybí bash nebo rsync")
    return subprocess.run(["bash", str(disk_root / script_filename(slug)), "to-nas", str(disk_root), str(target),
                           "--yes"], capture_output=True, text=True, errors="replace", stdin=subprocess.DEVNULL,
                          timeout=60, start_new_session=True)


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
    assert (pair_dir / ".sync-plan").read_text().startswith("PLAN=")
    t = pairs_db.last_transfer(st.pair["id"], "disk")
    assert t["status"] == "done" and t["files_done"] == 2 and t["failed"] == 0
    assert pairs_db.last_transfer(st.pair["id"], "direct") is None

    # zkopírované soubory jsou v záložce Na disku, ne v Kopírovat (podruhé se kopírovat nebudou)
    plan = load_overview().get(st.pair["id"]).plan
    assert not plan.selected and len(plan.comparison.ondisk) == 2

    r = _to_nas(disk_root, slug, root / "tgt")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "VAROVÁNÍ" not in r.stdout                                         # plán na disku sedí se skriptem
    assert (root / "tgt/Seriál (2019)/Season 01/S01E01.mkv").read_bytes() == b"prvni dil"

    # nový sken NAS2 (Aktualizovat) záložku Na disku vyprázdní — pravdu má sken
    runner.start_pair(st.pair["id"])
    wait_for_scans()
    plan = load_overview().get(st.pair["id"]).plan
    assert pairs_db.ondisk_for_pair(st.pair["id"]) == set() and not plan.comparison.ondisk and not plan.transfer


def test_disk_filled_in_batches_without_duplicates(temp_db, disk_root):
    from app import db

    root = temp_db
    for i in range(1, 5):
        write_file(root, f"src/dil {i}.mkv", bytes([i]) * 100)
    st = _pair(root)
    pid, slug = st.pair["id"], st.pair["slug"]
    db.set_setting("disk_capacity", "250")                                     # vejdou se 2 soubory

    st = load_overview().get(pid)
    assert [i.key for i in st.plan.selected] == ["dil 1.mkv", "dil 2.mkv"] and len(st.plan.deferred) == 2
    _start(st)
    wait_for_transfer()

    # další dávka: Kopírovat se přepočítá z Odloženo, zkopírované jsou Na disku
    st = load_overview().get(pid)
    assert [i.key for i in st.plan.selected] == ["dil 3.mkv", "dil 4.mkv"] and not st.plan.deferred
    assert sorted(i.key for i in st.plan.comparison.ondisk) == ["dil 1.mkv", "dil 2.mkv"]
    _start(st)
    wait_for_transfer()
    st = load_overview().get(pid)
    assert not st.plan.selected and len(st.plan.comparison.ondisk) == 4

    # skript na disku obsahuje obě dávky → to-nas přenese všechno
    r = _to_nas(disk_root, slug, root / "tgt")
    assert r.returncode == 0 and "VAROVÁNÍ" not in r.stdout, r.stdout + r.stderr
    assert sorted(p.name for p in (root / "tgt").iterdir()) == [f"dil {i}.mkv" for i in range(1, 5)]


def test_resume_after_cancel(temp_db, disk_root, monkeypatch):
    monkeypatch.setattr(transfer_module, "CHUNK", 4096)
    root = temp_db
    big = os.urandom(6 * 1024 * 1024)
    write_file(root, "src/a.mkv", b"hotovy")
    write_file(root, "src/b.bin", big)
    st = _pair(root)
    pid = st.pair["id"]
    pair_dir = disk_root / st.pair["slug"]

    assert _start(st)
    transfer_runner.cancel(pid)
    wait_for_transfer()
    t = pairs_db.last_transfer(pid, "disk")
    assert t["status"] == "cancelled"
    assert "b.bin" not in pairs_db.ondisk_for_pair(pid)                       # nedokončený soubor není Na disku
    assert (pair_dir / ".sync-plan").exists()                                  # skript popisuje, co na disku je

    # b.bin napůl (jako po výpadku) → další spuštění naváže
    write_file(pair_dir, ".b.bin.syncpart", big[: 2 * 1024 * 1024])
    (pair_dir / "b.bin").unlink(missing_ok=True)
    assert _start(load_overview().get(pid))
    wait_for_transfer()
    t = pairs_db.last_transfer(pid, "disk")
    assert t["status"] == "done" and "Navazuji b.bin" in t["log"]
    assert (pair_dir / "b.bin").read_bytes() == big
    assert pairs_db.ondisk_for_pair(pid) == {"a.mkv", "b.bin"}


def test_file_already_on_disk_is_skipped(temp_db, disk_root):
    root = temp_db
    write_file(root, "src/a.mkv", b"hotovy")
    write_file(root, "src/b.mkv", b"novy")
    st = _pair(root)
    pair_dir = disk_root / st.pair["slug"]
    write_file(pair_dir, "a.mkv", b"hotovy")                                   # např. po ručním kopírování
    assert _start(st)
    wait_for_transfer()
    t = pairs_db.last_transfer(st.pair["id"], "disk")
    assert "Už bylo na cíli (přeskočeno): 1" in t["log"]
    assert [(path, status) for _, path, status, _ in t["items"]] == [("a.mkv", "skipped"), ("b.mkv", "ok")]


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
        assert "disk_nothing" in start()                                      # vše už je Na disku


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


def test_second_disk_gets_only_its_batch_and_queue_can_be_cleared(temp_db, disk_root, tmp_path, monkeypatch):
    from app import db

    root = temp_db
    for i in range(1, 5):
        write_file(root, f"src/dil {i}.mkv", bytes([i]) * 100)
    st = _pair(root)
    pid, slug = st.pair["id"], st.pair["slug"]
    db.set_setting("disk_capacity", "250")
    _start(load_overview().get(pid))                                           # 1. disk: díly 1–2
    wait_for_transfer()

    disk2 = tmp_path / "disk2"                                                 # připojen jiný (prázdný) disk
    disk2.mkdir()
    monkeypatch.setattr(settings, "disk_path", disk2)
    _start(load_overview().get(pid))                                           # 2. disk: díly 3–4
    wait_for_transfer()
    assert sorted(p.name for p in (disk2 / slug).iterdir() if not p.name.startswith(".")) == ["dil 3.mkv", "dil 4.mkv"]
    assert len(load_overview().get(pid).plan.comparison.ondisk) == 4           # Na disku: obě várky

    # skript na 2. disku zná jen soubory, které na něm jsou (jinak by to-nas hlásil chybějící)
    r = _to_nas(disk2, slug, root / "tgt")
    assert r.returncode == 0 and "Ve zdroji chybí" not in r.stdout, r.stdout + r.stderr
    assert sorted(p.name for p in (root / "tgt").iterdir()) == ["dil 3.mkv", "dil 4.mkv"]

    # ruční vyprázdnění fronty Na disku
    with TestClient(app) as client:
        assert "Vyprázdnit Na disku" in client.get(f"/pary/{pid}?tab=ondisk").text
        r = client.post(f"/pary/{pid}/na-disku/vyprazdnit", follow_redirects=False)
        assert "ondisk_cleared" in r.headers["location"]
    assert pairs_db.ondisk_for_pair(pid) == set()
