"""Přehled — páry, stav skenů, co je k přenosu, kapacita disku."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from app.apps.pairs import db as pairs_db
from app.apps.pairs.state import load_overview
from app.common import page_ctx, redirect, safe_next
from app.scan.runner import runner
from app.templates_engine import templates

router = APIRouter(tags=["overview"])


def _render(request: Request):
    ov = load_overview()
    template = "overview/_table.html" if request.headers.get("HX-Request") else "overview/index.html"
    return templates.TemplateResponse(request, template, page_ctx(request, current_tab="overview", ov=ov))


@router.get("/", response_class=HTMLResponse)
def overview_page(request: Request):
    return _render(request)


@router.post("/aktualizovat-vse")
def refresh_all():
    for pair in pairs_db.list_pairs():
        runner.start_pair(pair["id"])
    return redirect("/", "scan_all_started")


@router.post("/pary/{pair_id:int}/aktualizovat")
def refresh_pair(pair_id: int, next: str = Form("/")):
    started = runner.start_pair(pair_id)
    return redirect(safe_next(next), "scan_started" if started else "scan_running")


@router.post("/pary/{pair_id:int}/aktualizovat/{side}")
def refresh_side(pair_id: int, side: str, next: str = Form("/")):
    started = runner.start(pair_id, side) if side in ("source", "target") else None
    return redirect(safe_next(next), "scan_started" if started else "scan_running")


@router.post("/skeny/{scan_id:int}/zrusit")
def cancel_scan(scan_id: int, next: str = Form("/")):
    runner.cancel(scan_id)
    return redirect(safe_next(next), "scan_cancelled")


@router.post("/pary/{pair_id:int}/na-disk", response_class=HTMLResponse)
def toggle_on_disk(request: Request, pair_id: int, on_disk: str = Form("")):
    pairs_db.set_on_disk(pair_id, bool(on_disk))
    if request.headers.get("HX-Request"):
        return _render(request)
    return redirect("/")
