"""Naplánovaný přímý přenos: časové okno (i přes půlnoc), plánovač a pozastavení po konci okna."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.apps.pairs import db as pairs_db
from app.apps.pairs.state import load_overview
from app.main import app
from app.transfer import window as window_mod
from app.transfer.runner import transfer_runner
from app.transfer.scheduler import scheduler
from app.transfer.window import Window, parse, set_window

from .conftest import wait_for_scans, write_file
from .test_transfer import wait_for_transfer


def at(h: int, m: int = 0) -> datetime:
    return datetime(2026, 9, 25, h, m)


def test_window_over_midnight_and_same_day():
    night = parse("22:00-06:00")
    assert night.contains(at(22)) and night.contains(at(23, 59)) and night.contains(at(0)) and night.contains(at(5, 59))
    assert not night.contains(at(6)) and not night.contains(at(12)) and not night.contains(at(21, 59))
    assert night.end_after(at(23)) == datetime(2026, 9, 26, 6, 0)          # konec až druhý den
    assert night.end_after(at(1)) == datetime(2026, 9, 25, 6, 0)
    assert night.next_start(at(12)) == datetime(2026, 9, 25, 22, 0)
    assert night.label == "22:00–06:00"

    day = parse("9:30-17:00")
    assert day.contains(at(9, 30)) and day.contains(at(16, 59)) and not day.contains(at(17)) and not day.contains(at(8))
    assert parse("10:00-10:00") is None and parse("25:00-06:00") is None and parse("") is None


def test_set_window_validation(temp_db):
    assert set_window("22:00", "06:00") == Window(22 * 60, 6 * 60)
    assert window_mod.get_window().label == "22:00–06:00"
    with pytest.raises(ValueError):
        set_window("22:00", "22:00")
    assert set_window("", "") is None and window_mod.get_window() is None


def _pair_with_direct(root, names) -> dict:
    (root / "tgt").mkdir(exist_ok=True)
    for n in names:
        write_file(root, f"src/{n}", n.encode())
    pid = pairs_db.save_pair(None, {"name": "P", "source_host_id": None, "source_path": "src",
                                    "target_host_id": None, "target_path": "tgt"})
    from app.scan.runner import runner
    runner.start_pair(pid)
    wait_for_scans()
    pairs_db.set_direct(pid, names, marked=True)
    return load_overview().get(pid)


def _open_window_now():
    now = datetime.now()
    start, end = now - timedelta(hours=1), now + timedelta(hours=1)
    set_window(start.strftime("%H:%M"), end.strftime("%H:%M"))


def test_scheduler_runs_only_in_window_and_finishes_plan(temp_db):
    st = _pair_with_direct(temp_db, ["a.mkv", "b.mkv"])
    pid = st.pair["id"]
    pairs_db.set_scheduled(pid, True)

    set_window("22:00", "06:00")
    assert scheduler.tick(now=at(12)) is None                              # mimo okno nic
    _open_window_now()
    assert scheduler.tick() is not None                                    # v okně se spustí
    wait_for_transfer()
    assert (temp_db / "tgt/a.mkv").exists() and (temp_db / "tgt/b.mkv").exists()
    assert pairs_db.get_pair(pid)["scheduled"] == 0                        # vše přeneseno → plán hotový
    assert scheduler.tick() is None


class ClosingWindow:
    """Okno, které se zavře po prvním souboru (simulace konce okna uprostřed přenosu)."""
    label = "22:00–06:00"

    def __init__(self):
        self.calls = 0

    def contains(self, now):
        self.calls += 1
        return self.calls <= 1

    def end_after(self, now):
        return now


def test_window_end_pauses_after_current_file(temp_db):
    st = _pair_with_direct(temp_db, ["a.mkv", "b.mkv", "c.mkv"])
    pid = st.pair["id"]
    pairs_db.set_scheduled(pid, True)
    transfer_runner.start(st.pair, st.plan.comparison.direct, st.target.current["id"], window=ClosingWindow())
    wait_for_transfer()
    t = pairs_db.last_transfer(pid)
    assert t["status"] == "paused" and t["files_done"] == 1 and t["failed"] == 0
    assert "skončilo" in t["log"]
    assert len(pairs_db.direct_for_pair(pid)) == 2                         # zbytek čeká na další okno
    assert pairs_db.get_pair(pid)["scheduled"] == 1


def test_schedule_through_web(temp_db):
    root = temp_db
    write_file(root, "src/a.mkv", b"a")
    (root / "tgt").mkdir()
    with TestClient(app) as client:
        client.post("/nastaveni/pary", data={"name": "P", "source_host_id": "", "source_path": "src",
                                             "target_host_id": "", "target_path": "tgt"})
        client.post("/pary/1/aktualizovat", data={"next": "/"})
        wait_for_scans()
        client.post("/pary/1/vybrane", data={"key": ["a.mkv"], "action": "direct", "tab": "copy"})

        r = client.post("/pary/1/primy-prenos/naplanovat", follow_redirects=False)
        assert "schedule_no_window" in r.headers["location"]                  # bez okna naplánovat nejde
        assert 'data-confirm-alt="Naplánovat"' not in client.get("/pary/1").text

        r = client.post("/nastaveni/okno", data={"window_from": "22:00", "window_to": "22:00"}, follow_redirects=False)
        assert "window_invalid" in r.headers["location"]
        client.post("/nastaveni/okno", data={"window_from": "22:00", "window_to": "06:00"})
        assert "Teď: <strong>22:00–06:00</strong>" in client.get("/nastaveni").text

        page = client.get("/pary/1").text
        assert 'data-confirm-alt="Naplánovat"' in page and "/primy-prenos/naplanovat" in page
        r = client.post("/pary/1/primy-prenos/naplanovat", follow_redirects=False)
        assert "direct_scheduled" in r.headers["location"] and pairs_db.get_pair(1)["scheduled"] == 1
        page = client.get("/pary/1").text
        assert "Naplánovaný přímý přenos" in page and "okno 22:00–06:00" in page
        assert 'data-confirm-alt="Naplánovat"' not in page                     # už naplánováno
        assert "Naplánovaný přímý přenos · okno 22:00–06:00" in client.get("/").text

        client.post("/pary/1/primy-prenos/zrusit-plan")
        assert pairs_db.get_pair(1)["scheduled"] == 0
        assert "Naplánovaný přímý přenos" not in client.get("/pary/1").text


def test_running_scheduled_transfer_shows_window(temp_db):
    from app.transfer.runner import ActiveTransfer, TransferProgress

    st = _pair_with_direct(temp_db, ["a.mkv"])
    pid = st.pair["id"]
    progress = TransferProgress(files_total=2, bytes_total=100, current="a.mkv", current_no=1, current_size=50,
                                phase="Nahrávám")
    transfer_runner._active[pid] = ActiveTransfer(1, pid, progress, window=parse("22:00-06:00"))
    try:
        with TestClient(app) as client:
            assert "(naplánovaný)" in client.get("/").text
            detail = client.get(f"/pary/{pid}").text
            assert "naplánovaný, okno do 06:00" in detail
    finally:
        transfer_runner._active.pop(pid, None)
