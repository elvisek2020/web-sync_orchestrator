"""Detail páru — soubory po kategoriích, ruční vyřazení, volby páru, skript, CSV, log skenu."""
from __future__ import annotations

import csv
import io
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from app.common import page_ctx, redirect
from app.config import settings
from app.core.excludes import parse_patterns
from app.core.plan import Item, PairPlan
from app.core.script import generate_script, script_filename
from app.scan.runner import runner
from app.templates_engine import templates

from . import db as pairs_db
from .state import PairState, load_overview

router = APIRouter(tags=["pairs"])

PAGE_SIZE = 200
TABS = [
    ("copy", "Kopírovat"),
    ("conflict", "Konflikty"),
    ("extra", "Přebývá"),
    ("deferred", "Odloženo"),
    ("skipped", "Vyřazené"),
    ("problems", "Problémy"),
]
TAB_KEYS = {k for k, _ in TABS}


def tab_items(plan: PairPlan, tab: str) -> list[Item]:
    cmp = plan.comparison
    return {
        "copy": plan.selected if plan.on_disk else plan.transfer,
        "conflict": cmp.conflict,
        "extra": cmp.extra,
        "deferred": plan.deferred,
        "skipped": cmp.skipped,
        "problems": cmp.problems,
    }[tab]


def _filter(items: list[Item], q: str) -> list[Item]:
    if not q:
        return items
    needle = q.casefold()
    return [i for i in items if needle in i.key.casefold()]


def side_desc(pair: dict, side: str) -> str:
    host = pair[f"{side}_host_name"]
    path = pair[f"{side}_path"]
    if host:
        return f"{host}:{path}"
    return f"{settings.local_root}/{path}".rstrip("/")


def _detail_ctx(request: Request, st: PairState, tab: str, q: str, page: int) -> dict:
    items = _filter(tab_items(st.plan, tab), q) if st.plan else []
    pages = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(page, 1), pages)
    counts = {k: len(tab_items(st.plan, k)) for k in TAB_KEYS} if st.plan else {}
    return page_ctx(
        request, current_tab="overview", st=st, pair=st.pair, plan=st.plan,
        tabs=TABS, tab=tab, q=q, page=page, pages=pages, counts=counts,
        items=items[(page - 1) * PAGE_SIZE: page * PAGE_SIZE], total=len(items),
        total_size=sum(i.size for i in items),
        scans=pairs_db.scans_for_pair(st.pair["id"]),
        source_desc=side_desc(st.pair, "source"), target_desc=side_desc(st.pair, "target"),
    )


def _load_state(pair_id: int) -> PairState | None:
    return load_overview().get(pair_id)


@router.get("/pary/{pair_id:int}", response_class=HTMLResponse)
def pair_detail(request: Request, pair_id: int, tab: str = "copy", q: str = "", page: int = 1):
    st = _load_state(pair_id)
    if not st:
        return redirect("/")
    tab = tab if tab in TAB_KEYS else "copy"
    target = request.headers.get("HX-Target")
    if request.headers.get("HX-Request") and target == "pair-sides" and not st.busy:
        # Sken doběhl → načíst celou stránku znovu, ať se přepočítá i plán.
        return Response(status_code=204, headers={"HX-Refresh": "true"})
    ctx = _detail_ctx(request, st, tab, q.strip(), page)
    if request.headers.get("HX-Request") and target in ("pair-files", "pair-body"):
        template = "pairs/_files.html" if target == "pair-files" else "pairs/_body.html"
        return templates.TemplateResponse(request, template, ctx)
    return templates.TemplateResponse(request, "pairs/detail.html", ctx)


def _after_change(request: Request, pair_id: int, tab: str, q: str, page: int):
    """Po změně výběru: HTMX dostane překreslené tělo stránky, bez JS přesměrování."""
    tab = tab if tab in TAB_KEYS else "copy"
    if request.headers.get("HX-Request"):
        st = _load_state(pair_id)
        if st:
            return templates.TemplateResponse(request, "pairs/_body.html", _detail_ctx(request, st, tab, q, page))
    return redirect(f"/pary/{pair_id}", tab=tab, q=q, page=page if page > 1 else None)


@router.post("/pary/{pair_id:int}/soubor", response_class=HTMLResponse)
def toggle_file(
    request: Request, pair_id: int,
    key: str = Form(...), include: str = Form(""),
    tab: str = Form("copy"), q: str = Form(""), page: int = Form(1),
):
    pairs_db.set_skips(pair_id, [key], skipped=not include)
    return _after_change(request, pair_id, tab, q, page)


@router.post("/pary/{pair_id:int}/hromadne", response_class=HTMLResponse)
def bulk_toggle(
    request: Request, pair_id: int,
    action: str = Form(...), tab: str = Form("copy"), q: str = Form(""),
):
    st = _load_state(pair_id)
    if st and st.plan and tab in TAB_KEYS and tab != "problems":
        keys = [item.key for item in _filter(tab_items(st.plan, tab), q.strip())]
        pairs_db.set_skips(pair_id, keys, skipped=(action == "skip"))
    return _after_change(request, pair_id, tab, q, 1)


@router.post("/pary/{pair_id:int}/volby")
def save_options(
    pair_id: int,
    include_conflicts: str = Form(""), include_extra: str = Form(""), exclude_patterns: str = Form(""),
):
    pairs_db.update_pair_options(
        pair_id, include_conflicts=bool(include_conflicts), include_extra=bool(include_extra),
        exclude_patterns="\n".join(parse_patterns(exclude_patterns)),
    )
    return redirect(f"/pary/{pair_id}", "saved")


@router.get("/pary/{pair_id:int}/skript")
def download_script(pair_id: int):
    st = _load_state(pair_id)
    if not st:
        return redirect("/")
    if not st.plan:
        return redirect(f"/pary/{pair_id}", "no_plan")
    if not st.plan.on_disk:
        return redirect(f"/pary/{pair_id}", "not_on_disk")
    script = generate_script(
        pair_name=st.pair["name"], slug=st.pair["slug"], plan=st.plan,
        source_desc=side_desc(st.pair, "source"), target_desc=side_desc(st.pair, "target"),
    )
    filename = script_filename(st.pair["slug"])
    return PlainTextResponse(
        script, media_type="text/x-shellscript; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/pary/{pair_id:int}/export.csv")
def export_csv(pair_id: int, tab: str = "copy", q: str = ""):
    st = _load_state(pair_id)
    if not st or not st.plan:
        return redirect(f"/pary/{pair_id}")
    tab = tab if tab in TAB_KEYS else "copy"
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["cesta", "velikost_bajty", "kategorie", "velikost_na_cili", "poznamka"])
    for item in _filter(tab_items(st.plan, tab), q.strip()):
        writer.writerow([item.display, item.size, item.category, item.tgt.size if item.tgt else "", item.problem or ""])
    filename = f"{st.pair['slug']}_{tab}.csv"
    return Response(
        "\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/skeny/{scan_id:int}", response_class=HTMLResponse)
def scan_page(request: Request, scan_id: int):
    scan = pairs_db.get_scan(scan_id)
    if not scan:
        return redirect("/")
    pair = pairs_db.get_pair(scan["pair_id"])
    job = runner.active(scan_id)
    if request.headers.get("HX-Request") and job is None:
        return Response(status_code=204, headers={"HX-Refresh": "true"})
    ctx = page_ctx(request, current_tab="overview", scan=scan, pair=pair, job=job,
                   live_log=job.progress.log_text() if job else None)
    template = "pairs/_scan_status.html" if request.headers.get("HX-Request") else "pairs/scan.html"
    return templates.TemplateResponse(request, template, ctx)
