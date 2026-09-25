"""Jinja2 šablony — globální proměnné a filtry."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi.templating import Jinja2Templates

from .config import TEMPLATES_DIR, VERSION_JSON, settings

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _load_version() -> str:
    try:
        return str(json.loads(VERSION_JSON.read_text(encoding="utf-8")).get("version", ""))
    except Exception:
        return ""


def filesize(value: Any) -> str:
    """Bajty → „1,2 GB“ (desítkové jednotky jako výrobci disků: 1 TB = 1000 GB)."""
    try:
        size = float(value or 0)
    except (TypeError, ValueError):
        return ""
    units = ["B", "kB", "MB", "GB", "TB"]
    i = 0
    while size >= 999.5 and i < len(units) - 1:
        size /= 1000
        i += 1
    if i == 0:
        return f"{int(size)} B"
    text = f"{size:.1f}" if size < 100 else f"{size:.0f}"
    return f"{text.replace('.', ',')} {units[i]}"


def number(value: Any) -> str:
    """12345 → „12 345“."""
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return str(value or "")


def cz_datetime(value: Any, seconds: bool = False) -> str:
    """ISO čas → „21. 9. 14:05“ (rok jen když není letošní; se seconds=True „21. 9. 14:05:07“)."""
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(str(value))
    except ValueError:
        return str(value)
    now = datetime.now()
    date = f"{dt.day}. {dt.month}." if dt.year == now.year else f"{dt.day}. {dt.month}. {dt.year}"
    return f"{date} {dt.strftime('%H:%M:%S' if seconds else '%H:%M')}"


def age(value: Any) -> str:
    """ISO čas → „před 5 min“, „před 3 h“, „před 2 dny“."""
    if not value:
        return ""
    try:
        seconds = (datetime.now() - datetime.fromisoformat(str(value))).total_seconds()
    except ValueError:
        return ""
    if seconds < 60:
        return "právě teď"
    if seconds < 3600:
        return f"před {int(seconds // 60)} min"
    if seconds < 86400:
        return f"před {int(seconds // 3600)} h"
    days = int(seconds // 86400)
    return "včera" if days == 1 else f"před {days} dny"


def duration(seconds: Any) -> str:
    try:
        s = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60} s"
    return f"{s // 3600} h {(s % 3600) // 60} min"


def cz_plural(count: int, one: str, few: str, many: str) -> str:
    """České skloňování podle počtu: 1 soubor, 2–4 soubory, 5+ souborů."""
    n = int(count or 0)
    word = one if n == 1 else few if 2 <= n <= 4 else many
    return f"{number(n)} {word}"


templates.env.globals["app_name"] = settings.app_name
templates.env.globals["app_version"] = _load_version()
templates.env.globals["now_dt"] = datetime.now
templates.env.filters["filesize"] = filesize
templates.env.filters["number"] = number
templates.env.filters["cz_datetime"] = cz_datetime
templates.env.filters["age"] = age
templates.env.filters["duration"] = duration
templates.env.filters["cz_plural"] = cz_plural
