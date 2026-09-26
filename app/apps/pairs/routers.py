"""Detail páru — soubory po kategoriích, ruční vyřazení, volby páru, skript, CSV, log skenu."""
from __future__ import annotations

import csv
import io
import json
import unicodedata
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response

from app.common import page_ctx, redirect
from app.config import settings
from app.core.excludes import parse_patterns
from app.core.plan import Item, PairPlan
from app.core.script import generate_script, script_filename
from app.scan.runner import runner
from datetime import datetime

from app.transfer import disk
from app.transfer.scheduler import scheduler
from app.transfer.window import get_window
from app.transfer.runner import split_items, transfer_runner
from app.templates_engine import templates

from . import db as pairs_db
from .state import PairState, load_overview

router = APIRouter(tags=["pairs"])

PAGE_SIZE = 50
TABS = [
    ("copy", "Kopírovat"),
    ("deferred", "Odloženo"),
    ("ondisk", "Na disku"),
    ("conflict", "Konflikty"),
    ("extra", "Přebývá"),
    ("skipped", "Vyřazené"),
    ("direct", "Přímý přenos"),
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
        "ondisk": cmp.ondisk,
        "skipped": cmp.skipped,
        "direct": cmp.direct,
        "problems": cmp.problems,
    }[tab]


def apply_action(pair_id: int, keys: list[str], action: str) -> None:
    """Akce nad označenými soubory: vyřadit / vrátit, přidat k přímému přenosu / odebrat."""
    if action in ("skip", "unskip"):
        pairs_db.set_skips(pair_id, keys, skipped=(action == "skip"))
    elif action in ("direct", "undirect"):
        pairs_db.set_direct(pair_id, keys, marked=(action == "direct"))


def direct_summary(plan: PairPlan | None) -> dict:
    """Co udělá přímý přenos: počet a velikost souborů k nahrání, počet ke smazání."""
    if not plan:
        return {"count": 0, "uploads": 0, "upload_bytes": 0, "deletions": 0}
    uploads, deletions = split_items(plan.comparison.direct)
    return {"count": len(uploads) + len(deletions), "uploads": len(uploads),
            "upload_bytes": sum(i.src.size for i in uploads), "deletions": len(deletions)}


def disk_summary(plan: PairPlan | None) -> dict:
    """Co zkopíruje přenos na disk: soubory záložky Kopírovat (přidělené na disk)."""
    items = plan.selected if plan and plan.on_disk else []
    return {"count": len(items), "bytes": sum(i.src.size for i in items)}


def _script_for(pair: dict, plan: PairPlan) -> str:
    return generate_script(
        pair_name=pair["name"], slug=pair["slug"], plan=plan,
        source_desc=side_desc(pair, "source"), target_desc=side_desc(pair, "target"),
    )


def _script(st: PairState) -> str:
    return _script_for(st.pair, st.plan)


# Řazení seznamu souborů: podle cesty nebo velikosti, „-“ = sestupně; prázdné = pořadí plánu.
SORTS = ("path", "-path", "size", "-size")


def _clean_sort(sort: str) -> str:
    return sort if sort in SORTS else ""


def _path_key(text: str) -> tuple[str, str]:
    """A–Z bez ohledu na velikost písmen a diakritiku (Čtyřlístek vedle Cheers, ne za Z)."""
    base = "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))
    return base.casefold(), text


def _sort(items: list[Item], sort: str) -> list[Item]:
    if sort in ("path", "-path"):
        return sorted(items, key=lambda i: _path_key(i.display), reverse=sort == "-path")
    if sort in ("size", "-size"):
        return sorted(items, key=lambda i: (i.size, _path_key(i.display)), reverse=sort == "-size")
    return items


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


def _detail_ctx(request: Request, st: PairState, tab: str, q: str, page: int, sort: str = "") -> dict:
    sort = _clean_sort(sort)
    items = _sort(_filter(tab_items(st.plan, tab), q), sort) if st.plan else []
    pages = max(1, (len(items) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(page, 1), pages)
    counts = {k: len(tab_items(st.plan, k)) for k in TAB_KEYS} if st.plan else {}
    return page_ctx(
        request, current_tab="overview", st=st, pair=st.pair, plan=st.plan,
        tabs=TABS, tab=tab, q=q, page=page, pages=pages, counts=counts, sort=sort,
        items=items[(page - 1) * PAGE_SIZE: page * PAGE_SIZE], total=len(items),
        total_size=sum(i.size for i in items),
        scans=pairs_db.scans_for_pair(st.pair["id"]),
        source_desc=side_desc(st.pair, "source"), target_desc=side_desc(st.pair, "target"),
        direct=direct_summary(st.plan), disk_plan=disk_summary(st.plan), job=st.transfer,
        disk_available=disk.disk_info()["mounted"], disk_dest=str(disk.pair_dir(st.pair)),
        script_name=script_filename(st.pair["slug"]),
        last_transfers=[] if st.transfer else pairs_db.last_transfers(st.pair["id"]),
        window=get_window(), now=datetime.now(),
    )


def _load_state(pair_id: int) -> PairState | None:
    return load_overview().get(pair_id)


@router.get("/pary/{pair_id:int}", response_class=HTMLResponse)
def pair_detail(request: Request, pair_id: int, tab: str = "copy", q: str = "", page: int = 1, sort: str = ""):
    st = _load_state(pair_id)
    if not st:
        return redirect("/")
    tab = tab if tab in TAB_KEYS else "copy"
    target = request.headers.get("HX-Target")
    if request.headers.get("HX-Request") and target == "pair-sides" and not st.busy:
        # Sken doběhl → načíst celou stránku znovu, ať se přepočítá i plán.
        return Response(status_code=204, headers={"HX-Refresh": "true"})
    ctx = _detail_ctx(request, st, tab, q.strip(), page, sort)
    if request.headers.get("HX-Request") and target in ("pair-files", "pair-body"):
        template = "pairs/_files.html" if target == "pair-files" else "pairs/_body.html"
        return templates.TemplateResponse(request, template, ctx)
    return templates.TemplateResponse(request, "pairs/detail.html", ctx)


def _after_change(request: Request, pair_id: int, tab: str, q: str, page: int, sort: str = ""):
    """Po změně výběru: HTMX dostane překreslené tělo stránky, bez JS přesměrování."""
    tab = tab if tab in TAB_KEYS else "copy"
    sort = _clean_sort(sort)
    if request.headers.get("HX-Request"):
        st = _load_state(pair_id)
        if st:
            ctx = dict(_detail_ctx(request, st, tab, q, page, sort), header_oob=True)   # i počty u tlačítek přenosů
            return templates.TemplateResponse(request, "pairs/_body.html", ctx)
    return redirect(f"/pary/{pair_id}", tab=tab, q=q, page=page if page > 1 else None, sort=sort)


@router.post("/pary/{pair_id:int}/vybrane", response_class=HTMLResponse)
def toggle_selected(
    request: Request, pair_id: int,
    key: list[str] = Form([]), action: str = Form("skip"),
    tab: str = Form("copy"), q: str = Form(""), page: int = Form(1), sort: str = Form(""),
):
    """Akce nad označenými soubory (vyřadit, vrátit, k přímému přenosu, odebrat z něj)."""
    apply_action(pair_id, key, action)
    return _after_change(request, pair_id, tab, q, page, sort)


@router.post("/pary/{pair_id:int}/hromadne", response_class=HTMLResponse)
def bulk_toggle(
    request: Request, pair_id: int,
    action: str = Form(...), tab: str = Form("copy"), q: str = Form(""), sort: str = Form(""),
):
    st = _load_state(pair_id)
    if st and st.plan and tab in TAB_KEYS and tab not in ("problems", "ondisk"):
        keys = [item.key for item in _filter(tab_items(st.plan, tab), q.strip())]
        apply_action(pair_id, keys, action)
    return _after_change(request, pair_id, tab, q, 1, sort)


# --- přímý přenos NAS → NAS ---

@router.post("/pary/{pair_id:int}/primy-prenos")
def start_direct(pair_id: int):
    st = _load_state(pair_id)
    if not st or not st.plan:
        return redirect(f"/pary/{pair_id}", "no_plan")
    if not st.direct_supported:
        return redirect(f"/pary/{pair_id}", "direct_local_only")
    if st.busy or st.transferring:
        return redirect(f"/pary/{pair_id}", "transfer_busy")
    items = st.plan.comparison.direct
    if not items:
        return redirect(f"/pary/{pair_id}", "direct_none")
    started = transfer_runner.start(st.pair, items, st.target.current["id"])
    return redirect(f"/pary/{pair_id}", "direct_started" if started else "transfer_busy")


@router.post("/pary/{pair_id:int}/primy-prenos/naplanovat")
def schedule_direct(pair_id: int):
    """Přímý přenos jen v časovém okně (z Nastavení) — i přes víc nocí, dokud se nepřenese všechno."""
    st = _load_state(pair_id)
    if not st or not st.plan:
        return redirect(f"/pary/{pair_id}", "no_plan")
    if not st.direct_supported:
        return redirect(f"/pary/{pair_id}", "direct_local_only")
    if not st.plan.comparison.direct:
        return redirect(f"/pary/{pair_id}", "direct_none")
    if get_window() is None:
        return redirect(f"/pary/{pair_id}", "schedule_no_window")
    pairs_db.set_scheduled(pair_id, True)
    scheduler.wake()                                   # je-li okno právě otevřené, začne hned
    return redirect(f"/pary/{pair_id}", "direct_scheduled")


@router.post("/pary/{pair_id:int}/primy-prenos/zrusit-plan")
def unschedule_direct(pair_id: int):
    pairs_db.set_scheduled(pair_id, False)
    return redirect(f"/pary/{pair_id}", "schedule_cancelled")


# --- přenos na disk (místo kroku to-disk skriptu) ---

@router.post("/pary/{pair_id:int}/prenos-na-disk")
def start_disk(pair_id: int):
    st = _load_state(pair_id)
    if not st or not st.plan:
        return redirect(f"/pary/{pair_id}", "no_plan")
    if not st.plan.on_disk:
        return redirect(f"/pary/{pair_id}", "not_on_disk")
    if st.busy or st.transferring:
        return redirect(f"/pary/{pair_id}", "transfer_busy")
    items = st.plan.selected
    if not items:
        return redirect(f"/pary/{pair_id}", "disk_nothing")
    if transfer_runner.disk_running():
        return redirect(f"/pary/{pair_id}", "disk_busy")
    problem = disk.disk_problem(items, disk.pair_dir(st.pair))
    if problem:
        return redirect(f"/pary/{pair_id}", problem)
    pair = st.pair
    started = transfer_runner.start_disk(
        pair, st.plan, script_name=script_filename(pair["slug"]),
        make_script=lambda plan: _script_for(pair, plan),
    )
    return redirect(f"/pary/{pair_id}", "disk_started" if started else "disk_busy")


@router.post("/pary/{pair_id:int}/na-disku/vyprazdnit")
def clear_ondisk(pair_id: int):
    """Ruční vyprázdnění záložky Na disku — soubory se vrátí do Kopírovat / Odloženo (bez skenu)."""
    pairs_db.clear_ondisk(pair_id)
    return redirect(f"/pary/{pair_id}", "ondisk_cleared", tab="copy")


@router.post("/pary/{pair_id:int}/prenos/zrusit")
def cancel_transfer(pair_id: int):
    transfer_runner.cancel(pair_id)
    return redirect(f"/pary/{pair_id}", "transfer_cancelled")


@router.post("/pary/{pair_id:int}/prenosy/{transfer_id:int}/odebrat", response_class=HTMLResponse)
def dismiss_transfer(request: Request, pair_id: int, transfer_id: int):
    """Odebere kartu posledního přenosu (záznam přenosu se smaže)."""
    pairs_db.delete_transfer(pair_id, transfer_id)
    if request.headers.get("HX-Request"):
        return HTMLResponse("")                     # karta zmizí na místě
    return redirect(f"/pary/{pair_id}")


@router.get("/pary/{pair_id:int}/prenos", response_class=HTMLResponse)
def transfer_panel(request: Request, pair_id: int):
    """Panel průběhu (HTMX se ptá každou sekundu, dokud přenos běží)."""
    job = transfer_runner.active(pair_id)
    if request.headers.get("HX-Request") and job is None:
        # přenos doběhl → celá stránka znovu (seznamy a čísla se změnily)
        return Response(status_code=204, headers={"HX-Refresh": "true"})
    pair = pairs_db.get_pair(pair_id)
    return templates.TemplateResponse(request, "pairs/_transfer.html", {
        "request": request, "pair": pair, "job": job,
        "last_transfers": [] if job else pairs_db.last_transfers(pair_id),
        "script_name": script_filename(pair["slug"]) if pair else "",
        "window": get_window(),
    })


@router.post("/pary/{pair_id:int}/volby", response_class=HTMLResponse)
def save_options(
    request: Request, pair_id: int,
    on_disk: str = Form(""), include_conflicts: str = Form(""), include_extra: str = Form(""),
    exclude_patterns: str = Form(""), tab: str = Form("copy"), q: str = Form(""), sort: str = Form(""),
):
    """Volby se ukládají hned při změně (HTMX); bez JS klasicky s přesměrováním."""
    before = pairs_db.get_pair(pair_id)
    pairs_db.update_pair_options(
        pair_id, on_disk=bool(on_disk), include_conflicts=bool(include_conflicts), include_extra=bool(include_extra),
        exclude_patterns="\n".join(parse_patterns(exclude_patterns)),
    )
    if request.headers.get("HX-Request") and before and bool(before["on_disk"]) != bool(on_disk):
        # zahrnutí do přenosu mění i tlačítka v hlavičce (Přenos na disk, Stáhnout skript) → celá stránka
        return Response(status_code=204, headers={"HX-Refresh": "true"})
    if request.headers.get("HX-Request"):
        st = _load_state(pair_id)
        if st and st.plan:
            tab = tab if tab in TAB_KEYS else "copy"
            ctx = dict(_detail_ctx(request, st, tab, q.strip(), 1, sort), options_oob=True)
            return templates.TemplateResponse(
                request, "pairs/_body.html", ctx,
                headers={"HX-Trigger": json.dumps({"notify": {"message": "Volby uloženy.", "type": "success"}})},
            )
        return Response(status_code=204, headers={"HX-Refresh": "true"})
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
    script = _script(st)
    filename = script_filename(st.pair["slug"])
    return PlainTextResponse(
        script, media_type="text/x-shellscript; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/pary/{pair_id:int}/export.csv")
def export_csv(pair_id: int, tab: str = "copy", q: str = "", sort: str = ""):
    st = _load_state(pair_id)
    if not st or not st.plan:
        return redirect(f"/pary/{pair_id}")
    tab = tab if tab in TAB_KEYS else "copy"
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(["cesta", "velikost_bajty", "kategorie", "velikost_na_cili", "poznamka"])
    for item in _sort(_filter(tab_items(st.plan, tab), q.strip()), _clean_sort(sort)):
        writer.writerow([item.display, item.size, item.category, item.tgt.size if item.tgt else "", item.problem or ""])
    filename = f"{st.pair['slug']}_{tab}.csv"
    return Response(
        "\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}"},
    )


@router.get("/skeny/{scan_id:int}/log", response_class=HTMLResponse)
def scan_log(request: Request, scan_id: int):
    """Obsah rozbalovacího řádku skenu v detailu páru (načte se až při rozbalení)."""
    scan = pairs_db.get_scan(scan_id)
    job = runner.active(scan_id) if scan else None
    return templates.TemplateResponse(request, "pairs/_scan_log.html", {
        "request": request, "scan": scan, "job": job,
        "live_log": job.progress.log_text() if job else None,
    })


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
