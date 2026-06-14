"""Persistensi SQLite untuk konfigurasi sumber (config persist setelah reboot)."""
from __future__ import annotations

import os
import sqlite3
import threading
from typing import Any, Optional

from .config import settings

_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL UNIQUE,
    hls_url         TEXT NOT NULL,
    mode            TEXT NOT NULL DEFAULT 'auto',
    active_mode     TEXT,
    bitrate         INTEGER,
    audio           TEXT NOT NULL DEFAULT 'aac',
    rtsp_transport  TEXT NOT NULL DEFAULT 'tcp',
    source_codec    TEXT,
    width           INTEGER,
    height          INTEGER,
    last_error      TEXT,
    low_latency     INTEGER NOT NULL DEFAULT 0,
    fast_start      INTEGER NOT NULL DEFAULT 0,
    enabled         INTEGER NOT NULL DEFAULT 1,
    created_at      TEXT NOT NULL
);
"""


def _migrate() -> None:
    """Tambah kolom baru pada DB lama (idempoten)."""
    cur = _c().execute("PRAGMA table_info(sources)")
    cols = {r["name"] for r in cur.fetchall()}
    if "low_latency" not in cols:
        _c().execute("ALTER TABLE sources ADD COLUMN low_latency INTEGER NOT NULL DEFAULT 0")
    if "fast_start" not in cols:
        _c().execute("ALTER TABLE sources ADD COLUMN fast_start INTEGER NOT NULL DEFAULT 0")
    _c().commit()


def init() -> None:
    global _conn
    os.makedirs(os.path.dirname(settings.DB_PATH) or ".", exist_ok=True)
    _conn = sqlite3.connect(settings.DB_PATH, check_same_thread=False)
    _conn.row_factory = sqlite3.Row
    _conn.execute("PRAGMA journal_mode=WAL;")
    _conn.executescript(_SCHEMA)
    _conn.commit()
    _migrate()


def _c() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("database belum di-init()")
    return _conn


def insert(row: dict[str, Any]) -> None:
    cols = ", ".join(row.keys())
    ph = ", ".join("?" for _ in row)
    with _lock:
        _c().execute(f"INSERT INTO sources ({cols}) VALUES ({ph})", list(row.values()))
        _c().commit()


def update(id: str, fields: dict[str, Any]) -> None:
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    with _lock:
        _c().execute(f"UPDATE sources SET {sets} WHERE id = ?", [*fields.values(), id])
        _c().commit()


def get(id: str) -> Optional[sqlite3.Row]:
    cur = _c().execute("SELECT * FROM sources WHERE id = ?", (id,))
    return cur.fetchone()


def get_by_name(name: str) -> Optional[sqlite3.Row]:
    cur = _c().execute("SELECT * FROM sources WHERE name = ?", (name,))
    return cur.fetchone()


def list_all() -> list[sqlite3.Row]:
    cur = _c().execute("SELECT * FROM sources ORDER BY created_at")
    return cur.fetchall()


def delete(id: str) -> None:
    with _lock:
        _c().execute("DELETE FROM sources WHERE id = ?", (id,))
        _c().commit()
