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
    "not_on_disk": ("error", "Pár není zahrnutý do přenosu — zaškrtněte u něj „Zahrnout do přenosu“."),
    "no_plan": ("error", "Pár zatím nemá úspěšný sken obou stran."),
    "disk_read": ("success", "Kapacita nastavena podle volného místa na disku."),
    "disk_missing": ("error", "Disk není do kontejneru připojený — zadej kapacitu ručně."),
    "direct_started": ("success", "Přímý přenos spuštěn."),
    "direct_none": ("error", "K přímému přenosu není nic označeno."),
    "direct_busy": ("error", "Pár se právě skenuje nebo přenáší — počkej na dokončení."),
    "direct_local_only": ("error", "Přímý přenos jde jen z lokálně připojeného zdroje."),
    "direct_cancelled": ("info", "Přenos se ruší — rozpracovaný soubor příště naváže."),
    "transfer_cancelled": ("info", "Přenos se ruší — rozpracovaný soubor příště naváže."),
    "transfer_busy": ("error", "Pár se právě skenuje nebo přenáší — počkej na dokončení."),
    "transfer_running": ("info", "Probíhá přenos — pár se teď neskenuje."),
    "disk_started": ("success", "Přenos na disk spuštěn."),
    "disk_nothing": ("error", "Na disk není co kopírovat."),
    "disk_busy": ("error", "Na disk se právě kopíruje jiný pár — počkej na dokončení."),
    "disk_not_mounted": ("error", "Disk není do kontejneru připojený (DISK_PATH) — přenos na disk nejde spustit."),
    "disk_readonly": ("error", "Disk je do kontejneru připojený jen pro čtení — v docker-compose u /mnt/disk "
                               "odeber „:ro“ a kontejner znovu vytvoř."),
    "disk_suspicious": ("error", "Připojený „disk“ má méně než 20 GB — nejspíš to není přenosový disk. "
                                 "Zkontroluj připojení."),
    "disk_same_as_nas": ("error", "DISK_PATH je na stejném svazku jako NAS1 — to není přenosový disk. "
                                  "Zkontroluj připojení v docker-compose."),
    "disk_cleaned": ("success", "Disk vyčištěn."),
    "disk_clean_empty": ("info", "Na disku nejsou žádná data přenosu."),
    "disk_clean_busy": ("error", "Na disk se právě kopíruje — vyčistit ho jde až po dokončení přenosu."),
    "disk_clean_failed": ("error", "Disk se nepodařilo celý vyčistit — podrobnosti jsou v logu kontejneru."),
    "disk_full": ("error", "Na disku není dost volného místa — uvolni ho (třeba data z minulého kola), "
                           "nebo v Nastavení sniž kapacitu disku."),
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
