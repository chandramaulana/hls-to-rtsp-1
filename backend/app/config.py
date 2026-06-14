"""Konfigurasi aplikasi (dibaca dari environment variable)."""
from __future__ import annotations

import os


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


class Settings:
    # Lokasi & port go2rtc (RTSP server + orchestrator, pengganti MediaMTX)
    G2R_API_URL: str = os.environ.get("G2R_API_URL", "http://localhost:1984")
    # Host yang dipakai untuk MENYUSUN URL RTSP yang ditampilkan ke operator.
    RTSP_HOST: str = os.environ.get("RTSP_HOST", "localhost")
    RTSP_PORT: int = _int("RTSP_PORT", 8554)

    # Database
    DB_PATH: str = os.environ.get("DB_PATH", os.path.join(os.getcwd(), "data", "gateway.db"))

    # Binary
    FFPROBE_BIN: str = os.environ.get("FFPROBE_BIN", "ffprobe")

    # Reconcile-loop (go2rtc): cuma jaring pengaman agar stream tetap terdaftar.
    # go2rtc sendiri yang urus restart producer, jadi interval bisa longgar.
    WATCHDOG_ENABLED: bool = os.environ.get("WATCHDOG_ENABLED", "1") == "1"
    WATCHDOG_INTERVAL: int = _int("WATCHDOG_INTERVAL", 30)     # detik antar-cek reconcile

    # Kapasitas
    MAX_TRANSCODE: int = _int("MAX_TRANSCODE", 12)  # batas konkurensi transcode (Orin NX)

    # ffprobe timeout (detik)
    FFPROBE_TIMEOUT: int = _int("FFPROBE_TIMEOUT", 20)

    # GOP (frame antar-keyframe) untuk transcode/fast-start. 30 ≈ 1 detik @30fps →
    # play RTSP instan. Turunkan (mis. 15) untuk play lebih cepat, naikkan untuk hemat bitrate.
    GOP_FRAMES: int = _int("GOP_FRAMES", 30)


settings = Settings()
