"""Přímý přenos NAS → NAS (cíl jako lokální složka — stejné rozhraní jako SFTP)."""
from __future__ import annotations

import os
import time

from fastapi.testclient import TestClient

from app.apps.pairs import db as pairs_db
from app.apps.pairs.state import load_overview
from app.core.excludes import Excluder, INTERNAL_EXCLUDE_PATTERNS
from app.main import app
from app.scan.runner import runner
from app.transfer import runner as transfer_module
from app.transfer.runner import transfer_runner

from .conftest import wait_for_scans, write_file


def wait_for_transfer(timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while transfer_runner.any_running():
        if time.monotonic() > deadline:
            raise TimeoutError("Přenos nedoběhl.")
        time.sleep(0.02)


def _pair(root) -> int:
    (root / "src").mkdir(exist_ok=True)
    (root / "tgt").mkdir(exist_ok=True)
    return pairs_db.save_pair(None, {"name": "P", "source_host_id": None, "source_path": "src",
                                     "target_host_id": None, "target_path": "tgt"})


def _scan(pid):
    runner.start_pair(pid)
    wait_for_scans()
    return load_overview().get(pid)


def test_direct_upload_replace_delete_and_patch(temp_db):
    root = temp_db
    pid = _pair(root)
    write_file(root, "src/Nové/Film.mkv", b"new content")
    os.utime(root / "src/Nové/Film.mkv", (1_600_000_000, 1_600_000_000))
    write_file(root, "src/konflikt.mkv", b"verze z NAS1")
    write_file(root, "tgt/konflikt.mkv", b"stara")
    write_file(root, "tgt/stare/navic.avi", b"x")
    write_file(root, "src/shodny.mkv", b"s")
    write_file(root, "tgt/shodny.mkv", b"s")

    st = _scan(pid)
    keys = ["Nové/Film.mkv", "konflikt.mkv", "stare/navic.avi"]
    pairs_db.set_direct(pid, keys, marked=True)
    st = load_overview().get(pid)
    cmp = st.plan.comparison
    assert sorted(i.key for i in cmp.direct) == sorted(keys)
    assert not st.plan.selected and not st.plan.deletions and not cmp.extra   # mimo plán na disk

    assert transfer_runner.start(st.pair, cmp.direct, st.target.current["id"])
    wait_for_transfer()

    assert (root / "tgt/Nové/Film.mkv").read_bytes() == b"new content"
    assert os.stat(root / "tgt/Nové/Film.mkv").st_mtime == 1_600_000_000     # čas změny zachován
    assert (root / "tgt/konflikt.mkv").read_bytes() == b"verze z NAS1"
    assert not (root / "tgt/stare").exists()                                 # smazáno i s prázdnou složkou
    assert not [p for p in (root / "tgt").rglob("*.syncpart")]

    t = pairs_db.last_transfer(pid)
    assert t["status"] == "done" and t["files_done"] == 2 and t["deleted"] == 1 and t["failed"] == 0
    states = {path: status for _, path, status, _ in t["items"]}              # jak dopadl každý soubor
    assert states == {"Nové/Film.mkv": "ok", "konflikt.mkv": "ok", "stare/navic.avi": "deleted"}
    assert pairs_db.direct_for_pair(pid) == set()                            # hotové se odznačí
    cmp = load_overview().get(pid).plan.comparison                           # výsledek promítnut bez skenu
    assert not cmp.missing and not cmp.conflict and not cmp.extra and not cmp.direct
    assert cmp.same_count == 3


def test_cancel_then_resume(temp_db, monkeypatch):
    monkeypatch.setattr(transfer_module, "CHUNK", 4096)
    root = temp_db
    pid = _pair(root)
    data = os.urandom(8 * 1024 * 1024)
    write_file(root, "src/velky.bin", data)
    st = _scan(pid)
    pairs_db.set_direct(pid, ["velky.bin"], marked=True)
    st = load_overview().get(pid)

    transfer_runner.start(st.pair, st.plan.comparison.direct, st.target.current["id"])
    transfer_runner.cancel(pid)
    wait_for_transfer()
    t = pairs_db.last_transfer(pid)
    assert t["status"] == "cancelled"
    assert pairs_db.direct_for_pair(pid) == {"velky.bin"}                   # nedokončené zůstává označené
    assert not (root / "tgt/velky.bin").exists()                             # žádný napůl nahraný soubor

    # rozpracovaná část (jako po výpadku linky) → další běh naváže
    (root / "tgt/.velky.bin.syncpart").write_bytes(data[: 3 * 1024 * 1024])
    st = load_overview().get(pid)
    transfer_runner.start(st.pair, st.plan.comparison.direct, st.target.current["id"])
    wait_for_transfer()
    assert (root / "tgt/velky.bin").read_bytes() == data
    t = pairs_db.last_transfer(pid)
    assert t["status"] == "done" and "Navazuji velky.bin" in t["log"]


def test_missing_source_file_fails_only_that_item(temp_db):
    root = temp_db
    pid = _pair(root)
    write_file(root, "src/a.mkv", b"a")
    write_file(root, "src/b.mkv", b"b")
    st = _scan(pid)
    pairs_db.set_direct(pid, ["a.mkv", "b.mkv"], marked=True)
    os.remove(root / "src/a.mkv")                                            # mezitím zmizel ze zdroje
    st = load_overview().get(pid)
    transfer_runner.start(st.pair, st.plan.comparison.direct, st.target.current["id"])
    wait_for_transfer()
    t = pairs_db.last_transfer(pid)
    assert t["status"] == "done" and t["files_done"] == 1 and t["failed"] == 1
    failed = [(path, detail) for _, path, status, detail in t["items"] if status == "error"]
    assert len(failed) == 1 and failed[0][0] == "a.mkv" and failed[0][1]           # s důvodem chyby
    assert (root / "tgt/b.mkv").exists()
    assert pairs_db.direct_for_pair(pid) == {"a.mkv"}


def test_skip_and_direct_are_exclusive(temp_db):
    pid = _pair(temp_db)
    pairs_db.set_skips(pid, ["x"], skipped=True)
    pairs_db.set_direct(pid, ["x"], marked=True)
    assert pairs_db.skips_for_pair(pid) == set() and pairs_db.direct_for_pair(pid) == {"x"}
    pairs_db.set_skips(pid, ["x"], skipped=True)
    assert pairs_db.skips_for_pair(pid) == {"x"} and pairs_db.direct_for_pair(pid) == set()


def test_part_files_are_never_scanned():
    ex = Excluder(INTERNAL_EXCLUDE_PATTERNS)
    assert ex.excluded("Seriály/.S01E01.mkv.syncpart")
    assert not ex.excluded("Seriály/S01E01.mkv")


def test_direct_flow_through_web(temp_db):
    root = temp_db
    write_file(root, "src/a.mkv", b"aaa")
    write_file(root, "tgt/navic.mkv", b"x")
    with TestClient(app) as client:
        client.post("/nastaveni/pary", data={"name": "P", "source_host_id": "", "source_path": "src",
                                             "target_host_id": "", "target_path": "tgt"})
        client.post("/pary/1/aktualizovat", data={"next": "/"})
        wait_for_scans()
        assert "Přímý přenos" in client.get("/pary/1").text

        client.post("/pary/1/vybrane", data={"key": ["a.mkv"], "action": "direct", "tab": "copy"})
        client.post("/pary/1/hromadne", data={"action": "direct", "tab": "extra"})
        page = client.get("/pary/1?tab=direct").text
        assert "a.mkv" in page and "navic.mkv" in page and "Přímý přenos (2)" in page

        r = client.post("/pary/1/primy-prenos", follow_redirects=False)
        assert r.status_code == 302 and "direct_started" in r.headers["location"]
        wait_for_transfer()
        assert (root / "tgt/a.mkv").read_bytes() == b"aaa" and not (root / "tgt/navic.mkv").exists()

        panel = client.get("/pary/1/prenos")
        assert "Poslední přímý přenos" in panel.text and "nahráno 1 z 1" in panel.text
        assert "Datum a čas" in panel.text and "Nahráno" in panel.text and "Smazáno" in panel.text
        assert client.get("/pary/1/prenos", headers={"HX-Request": "true"}).headers.get("HX-Refresh") == "true"
        r = client.post("/pary/1/primy-prenos", follow_redirects=False)
        assert "direct_none" in r.headers["location"]                        # už není co přenést

        # kartu jde odebrat (stav „Hotovo“ je zároveň tlačítko)
        tid = pairs_db.last_transfer(1)["id"]
        r = client.post(f"/pary/1/prenosy/{tid}/odebrat", headers={"HX-Request": "true"})
        assert r.status_code == 200 and r.text == ""
        assert "Poslední přímý přenos" not in client.get("/pary/1").text

        # Aktualizovat → nový sken cíle; stav páru ukazuje sken, karta posledního přenosu zmizí
        time.sleep(1.1)                                                      # časy se ukládají po sekundách
        client.post("/pary/1/aktualizovat", data={"next": "/pary/1"})
        wait_for_scans()
        assert "Poslední přímý přenos" not in client.get("/pary/1").text


def test_pages_render_while_transfer_runs(temp_db):
    from app.transfer.runner import ActiveTransfer, TransferProgress

    root = temp_db
    write_file(root, "src/a.mkv", b"a")
    with TestClient(app) as client:
        client.post("/nastaveni/pary", data={"name": "P", "source_host_id": "", "source_path": "src",
                                             "target_host_id": "", "target_path": "tgt"})
        (root / "tgt").mkdir(exist_ok=True)
        client.post("/pary/1/aktualizovat", data={"next": "/"})
        wait_for_scans()
        progress = TransferProgress(files_total=3, bytes_total=1000, delete_total=2, files_done=1, bytes_done=400,
                                    current="Seriál/díl 2.mkv", current_no=2, current_size=500, current_done=100,
                                    phase="Nahrávám")
        progress.samples.extend([(time.monotonic() - 2, 0), (time.monotonic(), 400)])
        transfer_runner._active[1] = ActiveTransfer(99, 1, progress)          # simulace běžícího přenosu
        try:
            overview = client.get("/").text
            assert "Přímý přenos na NAS2 · 40 %" in overview and "Přenos 40 %" in overview
            detail = client.get("/pary/1").text
            assert "Zrušit přenos" in detail and "40,0 %" in detail and 'title="Seriál/díl 2.mkv"' in detail
            assert "2 z 3" in detail and "<strong>20 %</strong> · 100 B z 500 B" in detail
            # aktuální soubor, pak celkový průběh, souhrnné boxy až dole
            assert detail.index("transfer-bar-u2") < detail.index("transfer-bar-total") < detail.index("Rychlost")
            panel = client.get("/pary/1/prenos", headers={"HX-Request": "true"})
            assert panel.status_code == 200 and 'hx-trigger="every 1s"' in panel.text
            r = client.post("/pary/1/aktualizovat", data={"next": "/pary/1"}, follow_redirects=False)
            assert "transfer_running" in r.headers["location"]                  # během přenosu se neskenuje
        finally:
            transfer_runner._active.pop(1, None)
