"""YouTube stream URL resolver using yt-dlp.

Mendeteksi URL YouTube, lalu mengekstrak URL HLS asli (manifest m3u8)
untuk digunakan oleh go2rtc / ffmpeg.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger("ytstream")

# Daftar domain YouTube — bisa ditambah jika diperlukan
_YOUTUBE_DOMAINS = {
    "www.youtube.com",
    "m.youtube.com",
    "youtube.com",
    "youtu.be",
    "www.youtubekids.com",
    "youtubekids.com",
}


def is_youtube_url(url: str) -> bool:
    """Cek apakah URL berasal dari YouTube (termasuk shortlink youtu.be)."""
    url_lower = url.strip().lower()
    for domain in _YOUTUBE_DOMAINS:
        if domain in url_lower:
            return True
    return False


async def resolve_stream_url(youtube_url: str) -> str:
    """Ekstrak URL stream HLS dari YouTube live.

    Args:
        youtube_url: URL video/live YouTube.

    Returns:
        URL HLS (m3u8) yang bisa dipakai go2rtc / ffmpeg.

    Raises:
        RuntimeError: bila gagal mengekstrak URL.
    """
    import yt_dlp

    def _extract():
        opts = {
            "quiet": True,
            "no_warnings": True,
            "format": "best[ext=mp4]/best",
        }
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)

        title = info.get("title", "?")
        log.info("yt-dlp: '%s' (%s)", title, "LIVE" if info.get("is_live") else "VOD")

        # Prioritas 1: format terpilih punya URL langsung
        url = info.get("url")
        if url:
            return url

        # Prioritas 2: requested_formats (biasanya untuk DASH)
        req_fmts = info.get("requested_formats")
        if req_fmts:
            # Ambil yang video (biasanya index 0), lalu yang audio
            for f in req_fmts:
                furl = f.get("url")
                if furl and f.get("acodec") != "none":
                    return furl
            for f in req_fmts:
                furl = f.get("url")
                if furl:
                    return furl

        # Prioritas 3: cek format individu, cari m3u8_native / hls
        formats = info.get("formats") or []
        # Urutkan dari bitrate tertinggi
        sorted_fmts = sorted(
            (f for f in formats if f.get("protocol") in ("m3u8_native", "m3u8")),
            key=lambda f: f.get("tbr", 0) or 0,
            reverse=True,
        )
        if sorted_fmts:
            url = sorted_fmts[0].get("url")
            if url:
                return url

        # Prioritas 4: format apa pun yang punya URL
        for f in formats:
            url = f.get("url")
            if url:
                return url

        raise RuntimeError(
            f"yt-dlp: tidak bisa mengekstrak stream URL dari '{youtube_url}'"
        )

    try:
        import asyncio
        return await asyncio.to_thread(_extract)
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"yt-dlp gagal: {e}") from e
