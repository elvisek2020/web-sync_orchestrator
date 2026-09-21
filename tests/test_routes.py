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

    csv = client.get("/pary/1/export.csv?tab=extra")
    assert "Navic.mkv" in csv.text

    # kapacita menší než soubor → odloženo, skript bez souborů
    client.post("/nastaveni/disk", data={"capacity_gb": "0,000000001"})
    assert "Film (2001)/Film.mkv" in client.get("/pary/1?tab=deferred").text

    # pár není zahrnutý do přenosu → skript se nestáhne
    client.post("/pary/1/na-disk", data={})
    r = client.get("/pary/1/skript", follow_redirects=False)
    assert r.status_code == 302 and "not_on_disk" in r.headers["location"]

    scan_id = client.get("/pary/1").text.split("/skeny/")[1].split("/")[0]
    assert client.get(f"/skeny/{scan_id}").status_code == 200
    assert "Hotovo" in client.get(f"/skeny/{scan_id}/log").text
