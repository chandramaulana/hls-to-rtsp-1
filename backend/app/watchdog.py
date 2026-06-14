"""Reconcile-loop ringan untuk go2rtc.

go2rtc mengelola lifecycle & restart producer (FFmpeg) sendiri, dan bersifat
on-demand — jadi watchdog 'byte stagnan' ala MediaMTX tidak relevan lagi (byte
memang 0 saat tidak ada penonton; itu normal, bukan freeze).

Tugas yang tersisa: pastikan tiap stream enabled di DB tetap TERDAFTAR di go2rtc.
Bila go2rtc restart/crash lalu pulih (config kita tidak persist di go2rtc karena
ditambah via API), loop ini mendaftarkan ulang stream yang hilang.
"""
from __future__ import annotations

import asyncio
import logging

from . import database as db
from . import go2rtc, service
from .config import settings

log = logging.getLogger("watchdog")


async def _tick() -> None:
    try:
        existing = await go2rtc.list_streams()
    except go2rtc.Go2rtcError as e:
        log.warning("reconcile: gagal ambil daftar stream go2rtc: %s", e)
        return

    for r in db.list_all():
        row = dict(r)
        if not row["enabled"]:
            continue
        if row["name"] not in existing:
            log.info("reconcile: stream '%s' hilang dari go2rtc, daftar ulang", row["name"])
            try:
                await go2rtc.add_stream(row["name"], service._build_src(row))
            except go2rtc.Go2rtcError as e:
                log.error("reconcile: daftar ulang '%s' gagal: %s", row["name"], e)


async def run() -> None:
    log.info("reconcile-loop start (interval=%ss)", settings.WATCHDOG_INTERVAL)
    while True:
        try:
            await _tick()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.error("reconcile tick error: %s", e)
        await asyncio.sleep(settings.WATCHDOG_INTERVAL)
