"""Logika inti: gabungkan DB + ffprobe + builder source + go2rtc menjadi operasi sumber.

Mendukung 3 jenis sumber:
- hls: URL HLS (.m3u8) biasa
- youtube: URL YouTube (auto-resolve ke HLS via yt-dlp)
- file: file MP4 yang diupload (looping via go2rtc fileloop template)
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from . import database as db
from . import ffmpeg_cmd, go2rtc, probe
from . import ytstream as ytstream_mod
from .config import settings
from .models import SourceCreate, SourceOut, SourceUpdate, Status, SourceType

log = logging.getLogger("gateway")


class ConflictError(RuntimeError):
    pass


class NotFoundError(RuntimeError):
    pass


class CapacityError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rtsp_url(name: str) -> str:
    return f"rtsp://{settings.RTSP_HOST}:{settings.RTSP_PORT}/{name}"


def _build_src(row: dict[str, Any]) -> str:
    return ffmpeg_cmd.build_source(
        hls_url=row["hls_url"],
        active_mode=row["active_mode"] or "copy",
        audio=row.get("audio", "aac"),
        source_type=row.get("source_type", "hls"),
        low_latency=bool(row.get("low_latency", 0)),
        fast_start=bool(row.get("fast_start", 0)),
    )


async def _resolve_youtube_url(url: str) -> tuple[str, Optional[str]]:
    if not ytstream_mod.is_youtube_url(url):
        return url, None
    try:
        resolved = await ytstream_mod.resolve_stream_url(url)
        return resolved, url
    except RuntimeError:
        return url, url


def _count_active_transcode(exclude_id: Optional[str] = None) -> int:
    n = 0
    for r in db.list_all():
        if r["id"] == exclude_id or not r["enabled"]:
            continue
        if r["active_mode"] == "transcode" or r["fast_start"]:
            n += 1
    return n


def _is_encode(row: dict[str, Any]) -> bool:
    return (row.get("active_mode") == "transcode") or bool(row.get("fast_start"))


def _get_file_name(file_path: Optional[str]) -> Optional[str]:
    """Ambil nama file asli dari path (untuk display)."""
    if not file_path:
        return None
    return os.path.basename(file_path)


async def create_source(payload: SourceCreate) -> SourceOut:
    if db.get_by_name(payload.name):
        raise ConflictError(f"nama '{payload.name}' sudah dipakai")

    hls_url = payload.hls_url
    original_url = payload.original_url
    source_type = payload.source_type.value if hasattr(payload.source_type, "value") else payload.source_type
    file_path = payload.file_path

    # --- File source: langsung pakai path file, skip ffprobe (file lokal) ---
    if source_type == "file":
        source_codec, width, height = None, None, None
        if not file_path or not os.path.isfile(file_path):
            raise RuntimeError(f"file tidak ditemukan: {file_path}")
        # Probe file untuk metadata
        try:
            res = await probe.probe(file_path)
            source_codec, width, height = res.codec, res.width, res.height
        except RuntimeError as e:
            log.warning("file probe gagal: %s", e)

        active_mode = probe.decide_mode(payload.mode.value, source_codec)

        row_preview = {"active_mode": active_mode, "fast_start": 1 if payload.fast_start else 0}
        if _is_encode(row_preview) and _count_active_transcode() >= settings.MAX_TRANSCODE:
            raise CapacityError(
                f"batas konkurensi encode tercapai ({settings.MAX_TRANSCODE})"
            )

        sid = str(uuid.uuid4())
        row = {
            "id": sid,
            "name": payload.name,
            "hls_url": file_path,
            "original_url": None,
            "source_type": "file",
            "file_path": file_path,
            "mode": payload.mode.value,
            "active_mode": active_mode,
            "bitrate": payload.bitrate,
            "audio": payload.audio.value,
            "rtsp_transport": payload.rtsp_transport.value,
            "low_latency": 1 if payload.low_latency else 0,
            "fast_start": 1 if payload.fast_start else 0,
            "source_codec": source_codec,
            "width": width,
            "height": height,
            "last_error": None,
            "enabled": 1,
            "created_at": _now(),
        }
        db.insert(row)
        try:
            await go2rtc.add_stream(payload.name, _build_src(row))
        except go2rtc.Go2rtcError as e:
            db.update(sid, {"last_error": f"go2rtc: {e}"})
        return await get_source(sid)

    # --- HLS / YouTube source (existing logic) ---
    if ytstream_mod.is_youtube_url(hls_url):
        try:
            resolved, original_url = await _resolve_youtube_url(hls_url)
            hls_url = resolved
        except RuntimeError:
            pass

    source_codec = width = height = None
    last_error: Optional[str] = None
    try:
        res = await probe.probe(hls_url)
        source_codec, width, height = res.codec, res.width, res.height
    except RuntimeError as e:
        last_error = f"ffprobe: {e}"

    active_mode = probe.decide_mode(payload.mode.value, source_codec)

    row_preview = {"active_mode": active_mode, "fast_start": 1 if payload.fast_start else 0}
    if _is_encode(row_preview) and _count_active_transcode() >= settings.MAX_TRANSCODE:
        raise CapacityError(
            f"batas konkurensi encode tercapai ({settings.MAX_TRANSCODE})"
        )

    sid = str(uuid.uuid4())
    row = {
        "id": sid,
        "name": payload.name,
        "hls_url": hls_url,
        "original_url": original_url,
        "source_type": "hls",
        "file_path": None,
        "mode": payload.mode.value,
        "active_mode": active_mode,
        "bitrate": payload.bitrate,
        "audio": payload.audio.value,
        "rtsp_transport": payload.rtsp_transport.value,
        "low_latency": 1 if payload.low_latency else 0,
        "fast_start": 1 if payload.fast_start else 0,
        "source_codec": source_codec,
        "width": width,
        "height": height,
        "last_error": last_error,
        "enabled": 1,
        "created_at": _now(),
    }
    db.insert(row)

    try:
        await go2rtc.add_stream(payload.name, _build_src(row))
    except go2rtc.Go2rtcError as e:
        db.update(sid, {"last_error": f"go2rtc: {e}"})
    else:
        if last_error is None:
            db.update(sid, {"last_error": None})

    return await get_source(sid)


async def update_source(id: str, payload: SourceUpdate) -> SourceOut:
    row = db.get(id)
    if not row:
        raise NotFoundError(id)
    d = dict(row)

    changed: dict[str, Any] = {}
    if payload.hls_url is not None:
        changed["hls_url"] = payload.hls_url
    if payload.original_url is not None:
        changed["original_url"] = payload.original_url
    if payload.source_type is not None:
        st = payload.source_type.value if hasattr(payload.source_type, "value") else payload.source_type
        changed["source_type"] = st
    if payload.file_path is not None:
        changed["file_path"] = payload.file_path
    if payload.bitrate is not None:
        changed["bitrate"] = payload.bitrate
    if payload.audio is not None:
        changed["audio"] = payload.audio.value
    if payload.rtsp_transport is not None:
        changed["rtsp_transport"] = payload.rtsp_transport.value
    if payload.low_latency is not None:
        changed["low_latency"] = 1 if payload.low_latency else 0
    if payload.fast_start is not None:
        changed["fast_start"] = 1 if payload.fast_start else 0
    if payload.mode is not None:
        changed["mode"] = payload.mode.value

    merged = {**d, **changed}
    need_reprobe = False

    if payload.hls_url is not None:
        need_reprobe = True
        if ytstream_mod.is_youtube_url(changed["hls_url"]):
            try:
                resolved, orig = await _resolve_youtube_url(changed["hls_url"])
                changed["hls_url"] = resolved
                changed["original_url"] = orig
                merged.update(changed)
            except RuntimeError as e:
                changed["last_error"] = f"yt-dlp: {e}"

    if payload.mode is not None:
        need_reprobe = True

    if need_reprobe:
        target_url = merged["hls_url"]
        try:
            res = await probe.probe(target_url)
            changed["source_codec"] = res.codec
            changed["width"] = res.width
            changed["height"] = res.height
            merged.update(changed)
            changed["last_error"] = None
        except RuntimeError as e:
            changed["last_error"] = f"ffprobe: {e}"
        changed["active_mode"] = probe.decide_mode(merged["mode"], merged.get("source_codec"))
        merged["active_mode"] = changed["active_mode"]

    if _is_encode(merged) and not _is_encode(d):
        if _count_active_transcode(exclude_id=id) >= settings.MAX_TRANSCODE:
            raise CapacityError(f"batas konkurensi encode tercapai ({settings.MAX_TRANSCODE})")

    db.update(id, changed)

    final = dict(db.get(id))
    if final["enabled"]:
        try:
            await go2rtc.add_stream(final["name"], _build_src(final))
        except go2rtc.Go2rtcError as e:
            db.update(id, {"last_error": f"go2rtc: {e}"})

    return await get_source(id)


async def restart_source(id: str) -> SourceOut:
    row = db.get(id)
    if not row:
        raise NotFoundError(id)
    db.update(id, {"enabled": 1})
    final = dict(db.get(id))

    # Refresh YouTube URL jika perlu
    if final.get("original_url") and ytstream_mod.is_youtube_url(final["original_url"]):
        try:
            resolved, _ = await _resolve_youtube_url(final["original_url"])
            db.update(id, {"hls_url": resolved, "last_error": None})
            final["hls_url"] = resolved
        except RuntimeError as e:
            db.update(id, {"last_error": f"yt-dlp refresh: {e}"})

    await go2rtc.delete_stream(final["name"])
    await go2rtc.add_stream(final["name"], _build_src(final))
    db.update(id, {"last_error": None})
    return await get_source(id)


async def stop_source(id: str) -> SourceOut:
    row = db.get(id)
    if not row:
        raise NotFoundError(id)
    db.update(id, {"enabled": 0})
    await go2rtc.delete_stream(row["name"])
    return await get_source(id)


async def delete_source(id: str) -> None:
    row = db.get(id)
    if not row:
        raise NotFoundError(id)
    rdict = dict(row)
    await go2rtc.delete_stream(rdict["name"])

    # Hapus file fisik jika file source
    fpath = rdict.get("file_path")
    if fpath and os.path.isfile(fpath):
        try:
            os.remove(fpath)
            log.info("file dihapus: %s", fpath)
        except OSError as e:
            log.warning("gagal hapus file %s: %s", fpath, e)

    db.delete(id)


def _status_from_runtime(row: dict[str, Any], rt: Optional[dict[str, Any]]) -> Status:
    if not row["enabled"]:
        return Status.stopped
    if row.get("last_error"):
        return Status.error
    if rt is None:
        return Status.connecting
    return Status.ready


def _readers(rt: Optional[dict[str, Any]]) -> int:
    if not rt:
        return 0
    cons = rt.get("consumers")
    return len(cons) if isinstance(cons, list) else 0


def _to_out(row: dict[str, Any], rt: Optional[dict[str, Any]]) -> SourceOut:
    return SourceOut(
        id=row["id"],
        name=row["name"],
        hls_url=row["hls_url"],
        original_url=row.get("original_url"),
        source_type=SourceType(row.get("source_type", "hls")),
        file_path=row.get("file_path"),
        file_name=_get_file_name(row.get("file_path")),
        mode=row["mode"],
        active_mode=row.get("active_mode"),
        bitrate=row.get("bitrate"),
        audio=row.get("audio", "aac"),
        rtsp_transport=row.get("rtsp_transport", "tcp"),
        low_latency=bool(row.get("low_latency", 0)),
        fast_start=bool(row.get("fast_start", 0)),
        source_codec=row.get("source_codec"),
        width=row.get("width"),
        height=row.get("height"),
        status=_status_from_runtime(row, rt),
        last_error=row.get("last_error"),
        rtsp_url=_rtsp_url(row["name"]),
        ready=rt is not None and not row.get("last_error") and bool(row["enabled"]),
        bytes_received=0,
        readers=_readers(rt),
        created_at=row["created_at"],
    )


async def get_source(id: str) -> SourceOut:
    row = db.get(id)
    if not row:
        raise NotFoundError(id)
    try:
        rt = await go2rtc.get_stream(row["name"])
    except go2rtc.Go2rtcError:
        rt = None
    return _to_out(dict(row), rt)


async def list_sources() -> list[SourceOut]:
    try:
        streams = await go2rtc.list_streams()
    except go2rtc.Go2rtcError:
        streams = {}
    return [_to_out(dict(r), streams.get(r["name"])) for r in db.list_all()]


async def reconcile() -> None:
    try:
        existing = await go2rtc.list_streams()
    except go2rtc.Go2rtcError:
        existing = {}
    for r in db.list_all():
        row = dict(r)
        if not row["enabled"]:
            continue
        if row["name"] not in existing:
            try:
                await go2rtc.add_stream(row["name"], _build_src(row))
            except go2rtc.Go2rtcError as e:
                db.update(row["id"], {"last_error": f"reconcile: {e}"})
