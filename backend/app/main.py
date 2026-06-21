"""FastAPI app: API CRUD sumber + upload file MP4 + dashboard statis + watchdog."""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, JSONResponse
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

_DEFAULT_FRONTEND = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend")
)
FRONTEND_DIR = os.environ.get("FRONTEND_DIR", _DEFAULT_FRONTEND)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    os.makedirs(settings.UPLOADS_DIR, exist_ok=True)
    log.info("DB siap di %s", settings.DB_PATH)
    log.info("Uploads dir: %s", settings.UPLOADS_DIR)
    try:
        await service.reconcile()
        log.info("rekonsiliasi go2rtc selesai")
    except Exception as e:
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


app = FastAPI(title="HLS→RTSP Gateway", version="2.0", lifespan=lifespan)


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


# ---- Upload MP4 ----
_ALLOWED_EXT = {".mp4", ".mov", ".avi", ".mkv", ".ts", ".m4v"}
_MAX_UPLOAD = 50 * 1024 * 1024  # 50 MB


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or ".mp4")[1].lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(400, f"ekstensi tidak didukung: {ext} (terima: {', '.join(_ALLOWED_EXT)})")

    # Generate unique filename, simpan nama asli untuk display
    stem = str(uuid.uuid4())[:12]
    safe_name = f"{stem}{ext}"
    dst = os.path.join(settings.UPLOADS_DIR, safe_name)

    content = await file.read()
    if len(content) > _MAX_UPLOAD:
        raise HTTPException(413, f"file terlalu besar ({(len(content)/1024/1024):.1f}MB). Maks 50MB")

    with open(dst, "wb") as f:
        f.write(content)

    log.info("upload: %s → %s (%d bytes)", file.filename, dst, len(content))

    return JSONResponse({
        "status": "ok",
        "file_path": dst,
        "file_name": file.filename,
        "size": len(content),
    })


# ---- Sajikan file upload via /uploads/ (untuk preview dll) ----
if os.path.isdir(settings.UPLOADS_DIR):
    app.mount("/uploads", StaticFiles(directory=settings.UPLOADS_DIR), name="uploads")


# ---- Frontend statis ----
if os.path.isdir(FRONTEND_DIR):
    @app.get("/")
    async def index():
        return FileResponse(os.path.join(FRONTEND_DIR, "index.html"))

    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
