"""Klien HTTP untuk API go2rtc (pengganti MediaMTX).

Endpoint (diverifikasi langsung terhadap go2rtc 1.9.x):
  GET    /api/streams              → {name: {producers, consumers}}
  PUT    /api/streams?name=&src=   → add/update (idempoten)
  DELETE /api/streams?src=<name>   → hapus
  GET    /api/streams?src=<name>   → detail satu stream
"""
from __future__ import annotations

from typing import Any, Optional

import httpx

from .config import settings


class Go2rtcError(RuntimeError):
    pass


def _base() -> str:
    return settings.G2R_API_URL.rstrip("/")


async def add_stream(name: str, src: str) -> None:
    """Tambah/replace stream. PUT bersifat idempoten."""
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.put(f"{_base()}/api/streams", params={"name": name, "src": src})
        if r.status_code >= 300:
            raise Go2rtcError(f"add stream '{name}' gagal: {r.status_code} {r.text.strip()}")


async def delete_stream(name: str) -> None:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.delete(f"{_base()}/api/streams", params={"src": name})
        # 404 = sudah tidak ada → idempoten
        if r.status_code >= 300 and r.status_code != 404:
            raise Go2rtcError(f"delete stream '{name}' gagal: {r.status_code} {r.text.strip()}")


async def list_streams() -> dict[str, dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{_base()}/api/streams")
        if r.status_code >= 300:
            raise Go2rtcError(f"list streams gagal: {r.status_code} {r.text.strip()}")
        data = r.json()
        return data if isinstance(data, dict) else {}


async def get_stream(name: str) -> Optional[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{_base()}/api/streams", params={"src": name})
        if r.status_code == 404:
            return None
        if r.status_code >= 300:
            raise Go2rtcError(f"get stream '{name}' gagal: {r.status_code} {r.text.strip()}")
        return r.json()
