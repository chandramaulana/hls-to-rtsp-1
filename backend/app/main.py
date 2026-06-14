"""FastAPI app: API CRUD sumber HLS + dashboard statis + watchdog background task."""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import database as db
from . import service, watchdog
from .config import settings
from .models import SourceCreate, SourceOut, SourceUpdate

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("gateway")

# Lokasi frontend (relatif terhadap repo). Dapat di-override via FRONTEND_DIR.
_DEFAULT_FRONTEND = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
)
FRONTEND_DIR = os.environ.get("FRONTEND_DIR", _DEFAULT_FRONTEND)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    log.info("DB siap di %s", settings.DB_PATH)
    # Rekonsiliasi: daftarkan ulang stream di go2rtc dari konfigurasi tersimpan.
    try:
        await service.reconcile()
        log.info("rekonsiliasi go2rtc selesai")
    except Exception as e:  # noqa: BLE001
        log.error("rekonsiliasi gagal: %s", e)

    task = None
    if settings.WATCHDOG_ENABLED:
        task = asyncio.create_task(watchdog.run())
    try:
        yield
    finally:
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(title="HLS→RTSP Gateway", version="1.0", lifespan=lifespan)


# ---- API ----

@app.get("/health")
async def health():
    return {"status": "ok", "db": settings.DB_PATH, "go2rtc": settings.G2R_API_URL}


@app.get("/api/sources", response_model=list[SourceOut])
async def list_sources():
    return await service.list_sources()


@app.post("/api/sources", response_model=SourceOut, status_code=201)
async def create_source(payload: SourceCreate):
    try:
        return await service.create_source(payload)
    except service.ConflictError as e:
        raise HTTPException(409, str(e))
    except service.CapacityError as e:
        raise HTTPException(429, str(e))


@app.get("/api/sources/{id}", response_model=SourceOut)
async def get_source(id: str):
    try:
        return await service.get_source(id)
    except service.NotFoundError:
        raise HTTPException(404, "sumber tidak ditemukan")


@app.patch("/api/sources/{id}", response_model=SourceOut)
async def update_source(id: str, payload: SourceUpdate):
    try:
        return await service.update_source(id, payload)
    except service.NotFoundError:
        raise HTTPException(404, "sumber tidak ditemukan")
    except service.CapacityError as e:
        raise HTTPException(429, str(e))


@app.post("/api/sources/{id}/restart", response_model=SourceOut)
async def restart_source(id: str):
    try:
        return await service.restart_source(id)
    except service.NotFoundError:
        raise HTTPException(404, "sumber tidak ditemukan")


@app.post("/api/sources/{id}/stop", response_model=SourceOut)
async def stop_source(id: str):
    try:
        return await service.stop_source(id)
    except service.NotFoundError:
        raise HTTPException(404, "sumber tidak ditemukan")


@app.delete("/api/sources/{id}", status_code=204)
async def delete_source(id: str):
    try:
        await service.delete_source(id)
    except service.NotFoundError:
        raise HTTPException(404, "sumber tidak ditemukan")


# ---- Frontend statis ----
# Sajikan dashboard di root. Mount paling akhir agar tidak menutupi rute /api.
if os.path.isdir(FRONTEND_DIR):
    @app.get("/")
    async def index():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
