"""Bangun 'source string' go2rtc untuk tiap stream.

go2rtc memakai sintaks sumber ringkas:  ffmpeg:<INPUT>#<modul>=<param>#...
Karena go2rtc menolak source string ber-SPASI via API ("insecure"), semua flag
kompleks didefinisikan sebagai TEMPLATE di config/go2rtc.yaml dan di sini hanya
dirujuk namanya:
  #input=hlslive | hlslowlat     → flag FFmpeg sebelum -i (lihat go2rtc.yaml)
  #video=copy                    → passthrough (mode COPY, paling ringan)
  #raw=faststart_sw | faststart_hw → re-encode GOP pendek (transcode / fast-start)
  #audio=copy | aac | drop

Catatan bitrate: bila perlu bitrate kustom, itu sudah termasuk di template
faststart_* (default 2M sw / 4M hw). Bitrate per-stream dinamis tidak didukung
lewat template; ubah template bila butuh nilai lain.
"""
from __future__ import annotations

import subprocess
from functools import lru_cache


@lru_cache(maxsize=1)
def has_hw_encoder() -> bool:
    """True bila ffmpeg punya encoder hardware Jetson (h264_nvmpi) → pilih template HW."""
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
    low_latency: bool = False,
    fast_start: bool = False,
) -> str:
    """Kembalikan string source go2rtc untuk satu stream (tanpa spasi)."""
    parts = [f"ffmpeg:{hls_url}"]
    parts.append(f"#input={'hlslowlat' if low_latency else 'hlslive'}")

    if active_mode == "transcode" or fast_start:
        parts.append(f"#raw={'faststart_hw' if has_hw_encoder() else 'faststart_sw'}")
    else:
        parts.append("#video=copy")

    # CATATAN go2rtc: TIDAK ada nilai "#audio=drop". Untuk membuang audio, JANGAN
    # kirim modifier #audio= sama sekali (go2rtc menafsirkan 'drop' sebagai nama file
    # output → "Unable to choose output format for 'drop'" → stream 404).
    if audio == "copy":
        parts.append("#audio=copy")
    elif audio == "aac":
        parts.append("#audio=aac")
    # audio == "drop": tidak menambahkan apa pun (video-only)

    return "".join(parts)
