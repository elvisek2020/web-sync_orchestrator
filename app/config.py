"""Konfigurace aplikace z proměnných prostředí."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
VERSION_JSON = STATIC_DIR / "version.json"

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))


class Config:
    def __init__(self) -> None:
        self.app_name = os.environ.get("APP_NAME", "Sync Orchestrator")
        self.log_level = os.environ.get("LOG_LEVEL", "INFO").upper()
        self.database_path = Path(os.environ.get("DATABASE_PATH", str(DATA_DIR / "sync_orchestrator.db")))
        # Kořen lokálně připojeného NAS1 v kontejneru; cesty lokálních stran páru jsou relativní k němu.
        self.local_root = Path(os.environ.get("LOCAL_ROOT", "/mnt/nas1"))
        # Volitelně: přenosový disk připojený do kontejneru (jen pro zjištění volného místa).
        self.disk_path = Path(os.environ.get("DISK_PATH", "/mnt/disk"))

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.database_path}"


settings = Config()
