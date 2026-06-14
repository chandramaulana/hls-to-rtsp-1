"""Skema data (Pydantic) untuk sumber HLS dan respons API."""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator
import re


class Mode(str, Enum):
    auto = "auto"
    copy = "copy"
    transcode = "transcode"


class Audio(str, Enum):
    copy = "copy"
    aac = "aac"
    drop = "drop"


class Transport(str, Enum):
    tcp = "tcp"
    udp = "udp"


class Status(str, Enum):
    ready = "ready"
    connecting = "connecting"
    error = "error"
    stopped = "stopped"


_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


class SourceCreate(BaseModel):
    name: str = Field(..., description="Slug unik, dipakai sebagai path RTSP")
    hls_url: str
    mode: Mode = Mode.auto
    bitrate: Optional[int] = Field(None, description="kbps untuk transcode; null = ikuti sumber")
    audio: Audio = Audio.aac
    rtsp_transport: Transport = Transport.tcp
    low_latency: bool = Field(
        False,
        description="True = ikuti live-edge HLS (latency minimum). Default False = stabil "
        "(disarankan untuk CCTV/sumber playlist rewel).",
    )
    fast_start: bool = Field(
        False,
        description="True = re-encode dengan keyframe tiap 1 detik agar play RTSP instan "
        "(untuk sumber GOP-panjang yang lambat saat di-play). Menambah beban encode.",
    )

    @field_validator("name")
    @classmethod
    def _slug(cls, v: str) -> str:
        v = v.strip().lower()
        if not _SLUG_RE.match(v):
            raise ValueError(
                "name harus slug: huruf kecil/angka/_/-, awali huruf/angka, maks 63 char"
            )
        return v

    @field_validator("hls_url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("hls_url harus diawali http:// atau https://")
        return v


class SourceUpdate(BaseModel):
    hls_url: Optional[str] = None
    mode: Optional[Mode] = None
    bitrate: Optional[int] = None
    audio: Optional[Audio] = None
    rtsp_transport: Optional[Transport] = None
    low_latency: Optional[bool] = None
    fast_start: Optional[bool] = None

    @field_validator("hls_url")
    @classmethod
    def _url(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        v = v.strip()
        if not (v.startswith("http://") or v.startswith("https://")):
            raise ValueError("hls_url harus diawali http:// atau https://")
        return v


class SourceOut(BaseModel):
    id: str
    name: str
    hls_url: str
    mode: Mode
    active_mode: Optional[str] = None        # copy/transcode aktual yang dipilih
    target_codec: str = "h264"
    bitrate: Optional[int] = None
    audio: Audio
    rtsp_transport: Transport
    low_latency: bool = False
    fast_start: bool = False
    source_codec: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    status: Status = Status.stopped
    last_error: Optional[str] = None
    rtsp_url: Optional[str] = None
    # Metrik live dari go2rtc
    ready: bool = False
    bytes_received: int = 0
    readers: int = 0
    created_at: str
