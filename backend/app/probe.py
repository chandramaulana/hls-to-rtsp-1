"""Deteksi codec sumber HLS via ffprobe (logika mode `auto`)."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Optional

from .config import settings


@dataclass
class ProbeResult:
    codec: Optional[str]
    width: Optional[int]
    height: Optional[int]


async def probe(hls_url: str) -> ProbeResult:
    """Jalankan ffprobe pada stream video pertama. Lempar RuntimeError bila gagal."""
    cmd = [
        settings.FFPROBE_BIN,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height",
        "-of", "json",
        hls_url,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=settings.FFPROBE_TIMEOUT)
    except asyncio.TimeoutError:
        raise RuntimeError("ffprobe timeout — sumber tidak merespons")
    except FileNotFoundError:
        raise RuntimeError(f"ffprobe tidak ditemukan ('{settings.FFPROBE_BIN}')")

    if proc.returncode != 0:
        msg = err.decode("utf-8", "replace").strip() or "ffprobe gagal"
        raise RuntimeError(msg)

    try:
        data = json.loads(out.decode("utf-8", "replace"))
        stream = (data.get("streams") or [{}])[0]
    except (json.JSONDecodeError, IndexError):
        raise RuntimeError("ffprobe: tidak ada stream video terdeteksi")

    return ProbeResult(
        codec=stream.get("codec_name"),
        width=stream.get("width"),
        height=stream.get("height"),
    )


def decide_mode(declared_mode: str, codec: Optional[str]) -> str:
    """Tentukan mode aktual (copy/transcode) dari mode yang dipilih + codec sumber."""
    if declared_mode == "copy":
        return "copy"
    if declared_mode == "transcode":
        return "transcode"
    # auto: H.264 → copy, selain itu → transcode
    if codec == "h264":
        return "copy"
    return "transcode"
