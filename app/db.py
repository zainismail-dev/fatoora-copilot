"""SQLite storage. One file, no server. Swap for PostgreSQL later by changing this module only."""
from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('clerk', 'manager')),
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS invoices (
    id TEXT PRIMARY KEY,
    token TEXT NOT NULL,
    received_at TEXT NOT NULL,
    source TEXT NOT NULL,            -- upload | email | manual
    sender TEXT NOT NULL DEFAULT '',
    file_name TEXT NOT NULL DEFAULT '',
    file_path TEXT NOT NULL DEFAULT '',
    file_sha256 TEXT NOT NULL DEFAULT '',
    extracted_by TEXT NOT NULL DEFAULT '',   -- gemini | mistral | manual | cache:<provider>
    supplier_ar TEXT NOT NULL DEFAULT '',
    supplier_en TEXT NOT NULL DEFAULT '',
    supplier_vat_no TEXT NOT NULL DEFAULT '',
    invoice_no TEXT NOT NULL DEFAULT '',
    invoice_date TEXT NOT NULL DEFAULT '',
    currency TEXT NOT NULL DEFAULT 'SAR',
    subtotal REAL NOT NULL DEFAULT 0,
    vat REAL NOT NULL DEFAULT 0,
    total REAL NOT NULL DEFAULT 0,
    lines TEXT NOT NULL DEFAULT '[]',
    checks TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL,            -- manual | review | pending | approved | rejected
    reason TEXT NOT NULL DEFAULT '',
    decided_at TEXT NOT NULL DEFAULT '',
    decided_by TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status);
CREATE TABLE IF NOT EXISTS extraction_cache (
    sha256 TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

_lock = threading.Lock()
_path: Path | None = None


def init(path: Path) -> None:
    global _path
    _path = path
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect() as c:
        c.executescript(SCHEMA)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    if _path is None:
        raise RuntimeError("db.init() was not called")
    with _lock:
        conn = sqlite3.connect(_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


def query(sql: str, args: tuple = ()) -> list[dict[str, Any]]:
    with connect() as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def one(sql: str, args: tuple = ()) -> dict[str, Any] | None:
    rows = query(sql, args)
    return rows[0] if rows else None


def execute(sql: str, args: tuple = ()) -> None:
    with connect() as c:
        c.execute(sql, args)


def insert(table: str, row: dict[str, Any]) -> None:
    cols = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    execute(f"INSERT INTO {table} ({cols}) VALUES ({marks})", tuple(row.values()))


def update(table: str, key: str, key_value: Any, changes: dict[str, Any]) -> None:
    sets = ", ".join(f"{k} = ?" for k in changes)
    execute(f"UPDATE {table} SET {sets} WHERE {key} = ?", (*changes.values(), key_value))


def get_state(key: str, default: str = "") -> str:
    row = one("SELECT value FROM app_state WHERE key = ?", (key,))
    return row["value"] if row else default


def set_state(key: str, value: str) -> None:
    execute("INSERT INTO app_state (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
