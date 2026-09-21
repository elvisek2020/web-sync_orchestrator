"""Nastavení — páry, SSH hosté, kapacita disku, výchozí vzory."""
from __future__ import annotations

import logging
import os
import posixpath

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from app import db
from app.apps.pairs import db as pairs_db
from app.apps.pairs.state import get_capacity
from app.common import page_ctx, redirect
from app.config import settings
from app.core.excludes import DEFAULT_EXCLUDE_PATTERNS, parse_patterns
from app.scan.common import ScanError, cz_items
from app.scan.sftp import test_connection
from app.templates_engine import templates

from . import db as settings_db

logger = logging.getLogger("sync.settings")
router = APIRouter(tags=["settings"])


def _default_excludes_text() -> str:
    return db.get_setting("default_excludes", "\n".join(DEFAULT_EXCLUDE_PATTERNS))


@router.get("/nastaveni", response_class=HTMLResponse)
def settings_page(request: Request):
    capacity = get_capacity()
    return templates.TemplateResponse(request, "settings/index.html", page_ctx(
        request, current_tab="settings",
        pairs=pairs_db.list_pairs(), hosts=settings_db.list_hosts(),
        capacity_gb=f"{capacity / 1e9:g}".replace(".", ",") if capacity else "",
        default_excludes=_default_excludes_text(), local_root=str(settings.local_root),
    ))


# --- disk a vzory ---

@router.post("/nastaveni/disk")
def save_capacity(capacity_gb: str = Form("")):
    value = capacity_gb.strip().replace(" ", "").replace(",", ".")
    try:
        gb = float(value) if value else 0.0
    except ValueError:
        gb = 0.0
    db.set_setting("disk_capacity", str(int(max(gb, 0) * 1e9)))
    return redirect("/nastaveni", "saved")


@router.post("/nastaveni/vzory")
def save_excludes(default_excludes: str = Form(""), reset: str = Form("")):
    text = "\n".join(DEFAULT_EXCLUDE_PATTERNS) if reset else "\n".join(parse_patterns(default_excludes))
    db.set_setting("default_excludes", text)
    return redirect("/nastaveni", "saved")


# --- páry ---

def _clean_local_path(path: str) -> str | None:
    """Relativní cesta pod LOCAL_ROOT; None, když by vedla ven."""
    rel = posixpath.normpath("/" + path.strip()).lstrip("/")
    if rel in ("", "."):
        return ""
    if rel.startswith(".."):
        return None
    return rel


def _clean_remote_path(path: str) -> str:
    # normpath by „//share“ nechal se dvěma lomítky (POSIX) — proto nejdřív lstrip
    return posixpath.normpath("/" + path.strip().lstrip("/"))


def _pair_form_ctx(request: Request, pair: dict | None, form: dict, error: str | None = None):
    return templates.TemplateResponse(request, "settings/pair_form.html", page_ctx(
        request, current_tab="settings", pair=pair, form=form, error=error,
        hosts=settings_db.list_hosts(), local_root=str(settings.local_root),
    ), status_code=400 if error else 200)


@router.get("/nastaveni/pary/novy", response_class=HTMLResponse)
def new_pair(request: Request):
    hosts = settings_db.list_hosts()
    form = {"name": "", "source_host_id": "", "source_path": "", "target_host_id": str(hosts[0]["id"]) if hosts else "", "target_path": ""}
    return _pair_form_ctx(request, None, form)


@router.get("/nastaveni/pary/{pair_id:int}", response_class=HTMLResponse)
def edit_pair(request: Request, pair_id: int):
    pair = pairs_db.get_pair(pair_id)
    if not pair:
        return redirect("/nastaveni")
    form = {k: ("" if pair[k] is None else str(pair[k])) for k in
            ("name", "source_host_id", "source_path", "target_host_id", "target_path")}
    return _pair_form_ctx(request, pair, form)


def _parse_pair_form(form: dict) -> tuple[dict | None, str | None]:
    name = form["name"].strip()
    if not name:
        return None, "Vyplňte název páru."
    data = {"name": name}
    for side, label in (("source", "zdroje"), ("target", "cíle")):
        host_id = int(form[f"{side}_host_id"]) if form[f"{side}_host_id"] else None
        if host_id and not settings_db.get_host_public(host_id):
            return None, f"Neznámý SSH host {label}."
        raw = form[f"{side}_path"]
        if not raw.strip():
            return None, f"Vyplňte cestu {label}."
        path = _clean_remote_path(raw) if host_id else _clean_local_path(raw)
        if path is None:
            return None, f"Cesta {label} musí být uvnitř {settings.local_root}."
        data[f"{side}_host_id"] = host_id
        data[f"{side}_path"] = path
    return data, None


@router.post("/nastaveni/pary")
@router.post("/nastaveni/pary/{pair_id:int}")
def save_pair(
    request: Request,
    pair_id: int | None = None,
    name: str = Form(""),
    source_host_id: str = Form(""),
    source_path: str = Form(""),
    target_host_id: str = Form(""),
    target_path: str = Form(""),
):
    form = {"name": name, "source_host_id": source_host_id, "source_path": source_path,
            "target_host_id": target_host_id, "target_path": target_path}
    pair = pairs_db.get_pair(pair_id) if pair_id else None
    data, error = _parse_pair_form(form)
    if not error:
        clash = db.query_one("SELECT id FROM pairs WHERE name = :n AND id <> :id", {"n": data["name"], "id": pair_id or 0})
        if clash:
            error = "Pár s tímto názvem už existuje."
    if error:
        return _pair_form_ctx(request, pair, form, error)
    pairs_db.save_pair(pair_id, data)
    return redirect("/nastaveni", "saved")


@router.post("/nastaveni/pary/{pair_id:int}/smazat")
def delete_pair(pair_id: int):
    pairs_db.delete_pair(pair_id)
    return redirect("/nastaveni", "deleted")


@router.post("/nastaveni/pary/{pair_id:int}/posunout")
def move_pair(pair_id: int, direction: int = Form(0)):
    pairs_db.move_pair(pair_id, -1 if direction < 0 else 1)
    return redirect("/nastaveni")


def _test_side(host_id: str, path: str) -> tuple[bool, str]:
    if not path.strip():
        return False, "Cesta není vyplněná."
    if host_id:
        host = settings_db.get_host_secret(int(host_id))
        if not host:
            return False, "Neznámý host."
        try:
            return True, test_connection(host, _clean_remote_path(path))
        except ScanError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Chyba: {e}"
    rel = _clean_local_path(path)
    if rel is None:
        return False, f"Cesta musí být uvnitř {settings.local_root}."
    full = settings.local_root / rel
    if not full.is_dir():
        return False, f"Složka {full} neexistuje."
    try:
        count = len(os.listdir(full))
    except OSError as e:
        return False, f"Složku {full} nelze přečíst: {e}"
    return True, f"Složka {full} existuje ({cz_items(count)})."


@router.post("/nastaveni/pary/test", response_class=HTMLResponse)
def test_pair_paths(
    request: Request,
    source_host_id: str = Form(""), source_path: str = Form(""),
    target_host_id: str = Form(""), target_path: str = Form(""),
):
    results = [
        ("Zdroj", *_test_side(source_host_id, source_path)),
        ("Cíl", *_test_side(target_host_id, target_path)),
    ]
    return templates.TemplateResponse(request, "settings/_test_result.html", {"request": request, "results": results})


# --- SSH hosté ---

def _host_form_ctx(request: Request, host: dict | None, form: dict, error: str | None = None):
    return templates.TemplateResponse(request, "settings/host_form.html", page_ctx(
        request, current_tab="settings", host=host, form=form, error=error,
    ), status_code=400 if error else 200)


@router.get("/nastaveni/hosty/novy", response_class=HTMLResponse)
def new_host(request: Request):
    return _host_form_ctx(request, None, {"name": "", "host": "", "port": "22", "username": ""})


@router.get("/nastaveni/hosty/{host_id:int}", response_class=HTMLResponse)
def edit_host(request: Request, host_id: int):
    host = settings_db.get_host_public(host_id)
    if not host:
        return redirect("/nastaveni")
    form = {k: str(host[k]) for k in ("name", "host", "port", "username")}
    return _host_form_ctx(request, host, form)


def _parse_host_form(name: str, host: str, port: str, username: str) -> tuple[dict | None, str | None]:
    if not name.strip() or not host.strip() or not username.strip():
        return None, "Vyplňte název, adresu a uživatele."
    try:
        port_num = int(port or 22)
        if not 0 < port_num < 65536:
            raise ValueError
    except ValueError:
        return None, "Port musí být číslo 1–65535."
    return {"name": name.strip(), "host": host.strip(), "port": port_num, "username": username.strip()}, None


@router.post("/nastaveni/hosty")
@router.post("/nastaveni/hosty/{host_id:int}")
def save_host(
    request: Request,
    host_id: int | None = None,
    name: str = Form(""), host: str = Form(""), port: str = Form("22"), username: str = Form(""),
    password: str = Form(""), keep_password: str = Form(""),
):
    existing = settings_db.get_host_public(host_id) if host_id else None
    form = {"name": name, "host": host, "port": port, "username": username}
    data, error = _parse_host_form(name, host, port, username)
    if not error:
        clash = db.query_one("SELECT id FROM hosts WHERE name = :n AND id <> :id", {"n": data["name"], "id": host_id or 0})
        if clash:
            error = "Host s tímto názvem už existuje."
    if error:
        return _host_form_ctx(request, existing, form, error)
    new_password = None if (existing and keep_password and not password) else password
    settings_db.save_host(host_id, password=new_password, **data)
    return redirect("/nastaveni", "saved")


@router.post("/nastaveni/hosty/{host_id:int}/smazat")
def delete_host(host_id: int):
    if settings_db.host_in_use(host_id):
        return redirect("/nastaveni", "host_in_use")
    settings_db.delete_host(host_id)
    return redirect("/nastaveni", "deleted")


@router.post("/nastaveni/hosty-test", response_class=HTMLResponse)
def test_host(
    request: Request,
    host_id: str = Form(""), host: str = Form(""), port: str = Form("22"), username: str = Form(""),
    password: str = Form(""),
):
    data, error = _parse_host_form("test", host, port, username)
    results = []
    if error:
        results.append(("Spojení", False, error))
    else:
        if not password and host_id:
            stored = settings_db.get_host_secret(int(host_id))
            password = stored["password"] if stored else ""
        try:
            results.append(("Spojení", True, test_connection(dict(data, password=password))))
        except ScanError as e:
            results.append(("Spojení", False, str(e)))
        except Exception as e:
            results.append(("Spojení", False, f"Chyba: {e}"))
    return templates.TemplateResponse(request, "settings/_test_result.html", {"request": request, "results": results})
