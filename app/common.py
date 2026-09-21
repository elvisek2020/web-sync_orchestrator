"""Společný kontext šablon a drobnosti pro routery."""
from __future__ import annotations

from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import RedirectResponse

# Zprávy po přesměrování — v URL je jen kód, text se nikdy nepřebírá z adresy.
FLASH_MESSAGES = {
    "scan_started": ("success", "Sken spuštěn."),
    "scan_all_started": ("success", "Skeny všech párů spuštěny."),
    "scan_running": ("info", "Sken už běží."),
    "scan_cancelled": ("info", "Sken se ruší."),
    "saved": ("success", "Uloženo."),
    "deleted": ("success", "Smazáno."),
    "not_on_disk": ("error", "Pár není zařazený na disk — zaškrtněte u něj „Na disk“."),
    "no_plan": ("error", "Pár zatím nemá úspěšný sken obou stran."),
    "disk_read": ("success", "Kapacita nastavena podle volného místa na disku."),
    "disk_missing": ("error", "Disk není do kontejneru připojený — zadej kapacitu ručně."),
    "host_in_use": ("error", "Host používá některý pár — nejdřív pár upravte nebo smažte."),
}


def page_ctx(request: Request, **kwargs) -> dict:
    flash = FLASH_MESSAGES.get(request.query_params.get("msg", ""))
    ctx = {
        "request": request,
        "current_tab": None,
        "hide_chrome": False,
        "flash": {"kind": flash[0], "text": flash[1]} if flash else None,
    }
    ctx.update(kwargs)
    return ctx


def redirect(path: str, msg: str | None = None, **params) -> RedirectResponse:
    query = {k: v for k, v in params.items() if v not in (None, "")}
    if msg:
        query["msg"] = msg
    sep = "&" if "?" in path else "?"
    url = f"{path}{sep}{urlencode(query)}" if query else path
    return RedirectResponse(url, status_code=302)


def safe_next(value: str | None, default: str = "/") -> str:
    """Návratová adresa jen v rámci aplikace (žádné //host ani absolutní URL)."""
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return default
