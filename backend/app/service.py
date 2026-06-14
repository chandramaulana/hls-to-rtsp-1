"""Logika inti: gabungkan DB + ffprobe + builder source + go2rtc menjadi operasi sumber.

DB = sumber kebenaran konfigurasi. go2rtc = RTSP server + orchestrator (on-demand).
Rekonsiliasi saat startup memastikan pemulihan total setelah reboot.

Catatan model go2rtc: stream bersifat ON-DEMAND — producer (FFmpeg) baru jalan saat
ada consumer pertama, lalu idle saat tidak ada penonton. Karena itu "status" di sini
berarti "terdaftar & siap" (bukan "byte sedang mengalir"). go2rtc mengelola lifecycle
& restart producer sendiri, jadi tak perlu watchdog byte-stagnan seperti pada MediaMTX.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from . import database as db
from . import ffmpeg_cmd, go2rtc, probe
from .config import settings
from .models import SourceCreate, SourceOut, SourceUpdate, Status


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
        low_latency=bool(row.get("low_latency", 0)),
        fast_start=bool(row.get("fast_start", 0)),
    )


def _count_active_transcode(exclude_id: Optional[str] = None) -> int:
    """Hitung stream yang membebani encoder (transcode ATAU fast_start = re-encode)."""
    n = 0
    for r in db.list_all():
        if r["id"] == exclude_id or not r["enabled"]:
            continue
        if r["active_mode"] == "transcode" or r["fast_start"]:
            n += 1
    return n


def _is_encode(row: dict[str, Any]) -> bool:
    return (row.get("active_mode") == "transcode") or bool(row.get("fast_start"))


async def create_source(payload: SourceCreate) -> SourceOut:
    if db.get_by_name(payload.name):
        raise ConflictError(f"nama '{payload.name}' sudah dipakai")

    source_codec = width = height = None
    last_error: Optional[str] = None
    try:
        res = await probe.probe(payload.hls_url)
        source_codec, width, height = res.codec, res.width, res.height
    except RuntimeError as e:
        last_error = f"ffprobe: {e}"

    active_mode = probe.decide_mode(payload.mode.value, source_codec)

    row_preview = {"active_mode": active_mode, "fast_start": 1 if payload.fast_start else 0}
    if _is_encode(row_preview) and _count_active_transcode() >= settings.MAX_TRANSCODE:
        raise CapacityError(
            f"batas konkurensi encode tercapai ({settings.MAX_TRANSCODE}); "
            "tolak untuk hindari overload encoder"
        )

    sid = str(uuid.uuid4())
    row = {
        "id": sid,
        "name": payload.name,
        "hls_url": payload.hls_url,
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

    if payload.hls_url is not None or payload.mode is not None:
        try:
            res = await probe.probe(merged["hls_url"])
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
            await go2rtc.add_stream(final["name"], _build_src(final))  # PUT = replace
        except go2rtc.Go2rtcError as e:
            db.update(id, {"last_error": f"go2rtc: {e}"})

    return await get_source(id)


async def restart_source(id: str) -> SourceOut:
    row = db.get(id)
    if not row:
        raise NotFoundError(id)
    db.update(id, {"enabled": 1})
    final = dict(db.get(id))
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
    await go2rtc.delete_stream(row["name"])
    db.delete(id)


def _status_from_runtime(row: dict[str, Any], rt: Optional[dict[str, Any]]) -> Status:
    if not row["enabled"]:
        return Status.stopped
    if row.get("last_error"):
        return Status.error
    if rt is None:
        # terdaftar di DB tapi belum ada di go2rtc → sedang/akan ditambahkan
        return Status.connecting
    # Terdaftar di go2rtc. On-demand: dianggap ready (siap melayani saat di-play).
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
        bytes_received=0,  # go2rtc on-demand: tidak ada byte saat idle (bukan indikator sehat)
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
    """Saat startup: pastikan tiap sumber enabled terdaftar di go2rtc (re-add bila hilang)."""
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
