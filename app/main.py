"""Sync Orchestrator — vstupní bod aplikace.

Páry NAS1 ↔ NAS2: tlačítko Aktualizovat přeskenuje obě strany, porovnání a plán se
dopočítají samy a výstupem je skript pro přenos přes disk.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.apps.overview.routers import router as overview_router
from app.apps.pairs.routers import router as pairs_router
from app.apps.settings.routers import router as settings_router
from app.config import STATIC_DIR, settings
from app.db import get_engine, init_db
from app.scan.runner import recover_interrupted

logging.basicConfig(
    level=getattr(logging, settings.log_level, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.getLogger("paramiko").setLevel(logging.WARNING)
logger = logging.getLogger("sync")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    interrupted = recover_interrupted()
    if interrupted:
        logger.warning("Po restartu označeno %d nedokončených skenů jako selhané.", interrupted)
    yield


app = FastAPI(title=settings.app_name, docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return response


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(overview_router)
app.include_router(pairs_router)
app.include_router(settings_router)


@app.get("/health")
def health():
    """Healthcheck pro Docker i reverzní proxy — ověřuje i databázi."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ok", "database": "connected"}
    except Exception:
        logger.exception("Health check: databáze nedostupná")
        return JSONResponse(status_code=503, content={"status": "error", "database": "disconnected"})
