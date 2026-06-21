"""Bangun 'source string' go2rtc untuk tiap stream.

Untuk HLS/YouTube: gunakan ffmpeg: dengan #input=hlslive template.
Untuk file MP4: gunakan exec: dengan command FFmpeg langsung (stream_loop -1).
"""
from __future__ import annotations

import subprocess
from functools import lru_cache


@lru_cache(maxsize=1)
def has_hw_encoder() -> bool:
    """True bila ffmpeg punya encoder hardware Jetson (h264_nvmpi) -> pilih template HW."""
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except (FileNotFoundError, subprocess.SubprocessError):
        return False
    return "h264_nvmpi" in out


def build_source(
    *,
    hls_url: str,
    active_mode: str,
    audio: str,
    source_type: str = "hls",
    low_latency: bool = False,
    fast_start: bool = False,
) -> str:
    """Kembalikan string source go2rtc untuk satu stream."""

    # Untuk file MP4: ffmpeg: langsung tanpa #input (stream sekali, restart on-demand)
    if source_type == "file":
        return "ffmpeg:" + hls_url + "#video=copy#audio=" + audio

    # Untuk HLS / YouTube: gunakan ffmpeg: dengan template
    parts = ["ffmpeg:" + hls_url]
    parts.append("#input=" + ("hlslowlat" if low_latency else "hlslive"))

    if active_mode == "transcode" or fast_start:
        parts.append("#raw=" + ("faststart_hw" if has_hw_encoder() else "faststart_sw"))
    else:
        parts.append("#video=copy")

    if audio == "copy":
        parts.append("#audio=copy")
    elif audio == "aac":
        parts.append("#audio=aac")

    return "".join(parts)
