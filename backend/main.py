"""
Sync Orchestrator - Main FastAPI application
"""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
import os

from backend.api import router as api_router
from backend.websocket_manager import websocket_manager
from backend.mount_service import mount_service
from backend.storage_service import storage_service

# Pro FastAPI 0.104+ použijeme lifespan místo on_event
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await mount_service.start_monitoring()
    await storage_service.initialize()
    yield
    # Shutdown
    await mount_service.stop_monitoring()
    await storage_service.cleanup()

app = FastAPI(title="Sync Orchestrator", version="1.0.0", lifespan=lifespan)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(api_router, prefix="/api")

# WebSocket endpoint
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket_manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            # Echo nebo zpracování zpráv od klienta
            await websocket_manager.broadcast({"type": "echo", "data": data})
    except WebSocketDisconnect:
        websocket_manager.disconnect(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        websocket_manager.disconnect(websocket)

# Static files (SPA)
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.exists(static_dir):
    # Mount static files (JS, CSS, assets)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.mount("/assets", StaticFiles(directory=os.path.join(static_dir, "assets")), name="assets")
    # Mount images
    images_dir = os.path.join(static_dir, "images")
    if os.path.exists(images_dir):
        app.mount("/images", StaticFiles(directory=images_dir), name="images")
    
    # SPA fallback - všechny ostatní cesty vrací index.html (musí být poslední route)
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # Pokud je to API, WebSocket, assets, static nebo images, neřeš to
        if full_path.startswith("api/") or full_path.startswith("ws") or full_path.startswith("assets/") or full_path.startswith("static/") or full_path.startswith("images/"):
            return {"error": "Not found"}
        
        index_path = os.path.join(static_dir, "index.html")
        if os.path.exists(index_path):
            return FileResponse(index_path)
        return {"error": "Frontend not built"}


