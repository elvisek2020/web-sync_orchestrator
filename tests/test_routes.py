"""Stránky se vykreslí a heslo SSH hosta se nikdy nevrátí do prohlížeče."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.apps.pairs import db as pairs_db
from app.apps.settings import db as settings_db
from app.main import app

from .conftest import wait_for_scans, write_file

SECRET = "tajne-heslo-12345"


@pytest.fixture()
def client(temp_db):
    with TestClient(app) as c:
        yield c


def test_empty_overview(client):
    r = client.get("/")
    assert r.status_code == 200 and "Zatím žádné páry" in r.text
    assert client.get("/health").json()["status"] == "ok"


def test_password_is_write_only(client):
    r = client.post("/nastaveni/hosty", data={"name": "NAS2", "host": "nas2.local", "port": "22",
                                              "username": "u", "password": SECRET}, follow_redirects=False)
    assert r.status_code == 302
    host_id = settings_db.list_hosts()[0]["id"]
    for url in ("/nastaveni", f"/nastaveni/hosty/{host_id}", "/nastaveni/pary/novy"):
        assert SECRET not in client.get(url).text, url
    # uložení bez hesla ponechá stávající
    client.post(f"/nastaveni/hosty/{host_id}", data={"name": "NAS2", "host": "nas2.local", "port": "22",
                                                    "username": "u2", "password": "", "keep_password": "1"})
    assert settings_db.get_host_secret(host_id)["password"] == SECRET


def test_full_cycle_local(client, temp_db):
    root = temp_db
    write_file(root, "src/Film (2001)/Film.mkv", b"12345")
    write_file(root, "src/Druhy/Druhy.mkv", b"123")
    (root / "tgt").mkdir()
    write_file(root, "tgt/Navic.mkv", b"1")

    r = client.post("/nastaveni/pary", data={"name": "Filmy", "source_host_id": "", "source_path": "src",
                                            "target_host_id": "", "target_path": "/tgt"}, follow_redirects=False)
    assert r.status_code == 302
    # cesta nemůže vést ven z kořene NAS1: „../etc“ se zkrátí na „etc“ uvnitř kořene
    client.post("/nastaveni/pary", data={"name": "Zlé", "source_host_id": "", "source_path": "../etc",
                                         "target_host_id": "", "target_path": "tgt"}, follow_redirects=False)
    assert pairs_db.get_pair(2)["source_path"] == "etc"
    pairs_db.delete_pair(2)
    missing = client.post("/nastaveni/pary", data={"name": "Bez cesty", "source_host_id": "", "source_path": " ",
                                                  "target_host_id": "", "target_path": "tgt"})
    assert missing.status_code == 400

    client.post("/pary/1/aktualizovat", data={"next": "/"})
    wait_for_scans()

    page = client.get("/")
    assert "Kopírovat" in page.text and "Filmy" in page.text
    detail = client.get("/pary/1")
    assert "Film (2001)/Film.mkv" in detail.text
    assert "Navic.mkv" in client.get("/pary/1?tab=extra").text

    # ruční vyřazení přežije další sken
    client.post("/pary/1/vybrane", data={"key": ["Druhy/Druhy.mkv"], "action": "skip", "tab": "copy", "q": "", "page": "1"})
    client.post("/pary/1/aktualizovat", data={"next": "/"})
    wait_for_scans()
    assert "Druhy/Druhy.mkv" in client.get("/pary/1?tab=skipped").text
    # vrácení označených a znovu vyřazení (výběr víc souborů najednou)
    client.post("/pary/1/vybrane", data={"key": ["Druhy/Druhy.mkv"], "action": "unskip", "tab": "skipped"})
    assert "Druhy/Druhy.mkv" not in client.get("/pary/1?tab=skipped").text
    client.post("/pary/1/vybrane", data={"key": ["Druhy/Druhy.mkv", "Film (2001)/Film.mkv"], "action": "skip"})
    assert "2" in client.get("/pary/1?tab=skipped").text.split('Vyřazené <span class="tabs-count">')[1][:3]
    client.post("/pary/1/vybrane", data={"key": ["Film (2001)/Film.mkv"], "action": "unskip"})

    script = client.get("/pary/1/skript")
    assert script.status_code == 200
    assert script.headers["content-disposition"] == 'attachment; filename="sync_filmy.sh"'
    assert script.text.startswith("#!/usr/bin/env bash") and "Kopírovat:        1 souborů" in script.text

    # export CSV je výchozí vypnutý, povolí se v Nastavení → Další volby
    assert client.get("/pary/1/export.csv?tab=extra").status_code == 404
    assert "/export.csv" not in client.get("/pary/1?tab=extra").text
    client.post("/nastaveni/volby", data={"csv_export": "1"})
    assert "/export.csv" in client.get("/pary/1?tab=extra").text
    csv = client.get("/pary/1/export.csv?tab=extra")
    assert "Navic.mkv" in csv.text

    # kapacita menší než soubor → odloženo, skript bez souborů
    client.post("/nastaveni/disk", data={"capacity_gb": "0,000000001"})
    assert "Film (2001)/Film.mkv" in client.get("/pary/1?tab=deferred").text

    # pár není zahrnutý do přenosu → skript se nestáhne
    client.post("/pary/1/volby", data={"include_conflicts": "1"})             # bez on_disk = nezahrnuto
    overview = client.get("/").text
    assert "zahrnuto do hromadného přenosu" not in overview                  # nezahrnutý pár bez poznámky
    r = client.get("/pary/1/skript", follow_redirects=False)
    assert r.status_code == 302 and "not_on_disk" in r.headers["location"]

    # Volby páru jsou vždy sbalené (bez open i bez zapamatování stavu)
    detail = client.get("/pary/1").text
    assert '<details class="card" id="pair-options">' in detail and "data-remember-open" not in detail

    scan_id = client.get("/pary/1").text.split("/skeny/")[1].split("/")[0]
    assert client.get(f"/skeny/{scan_id}").status_code == 200
    assert "Hotovo" in client.get(f"/skeny/{scan_id}/log").text


def test_options_autosave_and_cancel_pair(client, temp_db):
    import json

    from app.scan.runner import runner

    root = temp_db
    write_file(root, "src/a.mkv", b"12")
    write_file(root, "tgt/a.mkv", b"1")          # konflikt
    client.post("/nastaveni/pary", data={"name": "P", "source_host_id": "", "source_path": "src",
                                         "target_host_id": "", "target_path": "tgt"})
    client.post("/pary/1/aktualizovat", data={"next": "/"})
    wait_for_scans()

    # volby se ukládají přes HTMX: vrátí překreslené tělo, nový souhrn voleb (OOB) a toast
    r = client.post("/pary/1/volby", data={"on_disk": "1", "include_extra": "1", "tab": "conflict"},
                    headers={"HX-Request": "true"})
    assert r.status_code == 200 and 'id="pair-body"' in r.text
    assert 'hx-swap-oob="true"' in r.text and "konflikty se nepřenáší" in r.text
    assert json.loads(r.headers["HX-Trigger"])["notify"]["message"] == "Volby uloženy."
    assert pairs_db.get_pair(1)["include_conflicts"] == 0 and pairs_db.get_pair(1)["include_extra"] == 1

    # vypnutí „Zahrnout do přenosu“ mění i hlavičku stránky → celé překreslení
    r = client.post("/pary/1/volby", data={"include_extra": "1"}, headers={"HX-Request": "true"})
    assert r.status_code == 204 and r.headers["HX-Refresh"] == "true" and pairs_db.get_pair(1)["on_disk"] == 0
    client.post("/pary/1/volby", data={"on_disk": "1", "include_extra": "1"})

    # „Zrušit aktualizaci“ zruší oba skeny páru
    for i in range(300):
        write_file(root, f"src/d{i % 30}/f{i}.bin")
    runner.start_pair(1)
    r = client.post("/pary/1/zrusit", data={"next": "/pary/1"}, follow_redirects=False)
    assert r.status_code == 302 and "scan_cancelled" in r.headers["location"]
    wait_for_scans()
    statuses = {s["status"] for s in pairs_db.scans_for_pair(1)}
    assert statuses <= {"done", "cancelled"}


def test_disk_capacity_keeps_reserve():
    from app.transfer.disk import usable_capacity

    assert usable_capacity(513_054_605_312) == 507 * 10**9     # 1 % rezerva
    assert usable_capacity(50 * 10**9) == 49 * 10**9            # nejméně 1 GB
    assert usable_capacity(500 * 10**6) == 0


def test_stylesheet_braces_are_balanced():
    """Přebytečná „}“ na nejvyšší úrovni tiše zahodí následující pravidlo (tak zmizel .progress)."""
    from pathlib import Path

    css = (Path(__file__).parent.parent / "app/static/css/app.css").read_text(encoding="utf-8")
    depth = 0
    for n, line in enumerate(css.splitlines(), 1):
        depth += line.count("{") - line.count("}")
        assert depth >= 0, f"přebytečná závorka na řádku {n}"
    assert depth == 0


def test_file_list_sorting(temp_db):
    root = temp_db
    write_file(root, "src/Čtyřlístek.mkv", b"x" * 30)
    write_file(root, "src/cheers.mkv", b"x" * 10)
    write_file(root, "src/Zorro.mkv", b"x" * 20)
    (root / "tgt").mkdir()
    with TestClient(app) as client:
        client.post("/nastaveni/pary", data={"name": "P", "source_host_id": "", "source_path": "src",
                                             "target_host_id": "", "target_path": "tgt"})
        client.post("/pary/1/aktualizovat", data={"next": "/"})
        wait_for_scans()

        def order(sort: str) -> list[str]:
            html = client.get(f"/pary/1?tab=copy&sort={sort}").text
            names = ["cheers.mkv", "Čtyřlístek.mkv", "Zorro.mkv"]
            return sorted(names, key=lambda n: html.index(f'value="{n}"'))

        assert order("path") == ["cheers.mkv", "Čtyřlístek.mkv", "Zorro.mkv"]   # bez ohledu na velikost písmen a háčky
        assert order("-path") == ["Zorro.mkv", "Čtyřlístek.mkv", "cheers.mkv"]
        assert order("size") == ["cheers.mkv", "Zorro.mkv", "Čtyřlístek.mkv"]
        assert order("-size") == ["Čtyřlístek.mkv", "Zorro.mkv", "cheers.mkv"]
        html = client.get("/pary/1?tab=copy&sort=size").text
        assert 'aria-sort="ascending"' in html and "sort=-size" in html            # druhý klik = sestupně
        assert client.get("/pary/1?tab=copy&sort=nesmysl").status_code == 200    # neznámé řazení = výchozí

        # akce nad výběrem řazení zachová, CSV také řadí
        r = client.post("/pary/1/vybrane", data={"key": ["Zorro.mkv"], "action": "skip", "tab": "copy",
                                                 "sort": "-size"}, follow_redirects=False)
        assert "sort=-size" in r.headers["location"]
        client.post("/nastaveni/volby", data={"csv_export": "1"})
        csv_lines = client.get("/pary/1/export.csv?tab=copy&sort=-path").text.splitlines()[1:]
        assert [line.split(";")[0] for line in csv_lines] == ["Čtyřlístek.mkv", "cheers.mkv"]


def test_hidden_attribute_wins_over_display_classes():
    """Skryté druhé tlačítko v potvrzovacím okně (.btn má display: inline-flex) nesmí být vidět."""
    from pathlib import Path

    css = (Path(__file__).parent.parent / "app/static/css/app.css").read_text(encoding="utf-8")
    assert "[hidden] {\n    display: none !important;" in css
