"""SQLite idempotency journal: client_order_id → state + stored response. Survives restarts."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

IN_FLIGHT = "IN_FLIGHT"
DONE = "DONE"
UNKNOWN = "UNKNOWN"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS order_journal (
    client_order_id TEXT PRIMARY KEY,
    kind            TEXT NOT NULL,
    target          TEXT NOT NULL,
    state           TEXT NOT NULL,
    status_code     INTEGER,
    response_json   TEXT,
    request_json    TEXT NOT NULL,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class JournalEntry:
    client_order_id: str
    kind: str
    target: str
    state: str
    status_code: int | None
    response: dict[str, Any] | None
    request: dict[str, Any]


class Journal:
    def __init__(self, path: str) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def get(self, client_order_id: str) -> JournalEntry | None:
        with self._lock:
            row = self._db.execute(
                "SELECT client_order_id, kind, target, state, status_code, response_json,"
                " request_json FROM order_journal WHERE client_order_id = ?",
                (client_order_id,),
            ).fetchone()
        if row is None:
            return None
        return JournalEntry(
            client_order_id=row[0],
            kind=row[1],
            target=row[2],
            state=row[3],
            status_code=row[4],
            response=json.loads(row[5]) if row[5] else None,
            request=json.loads(row[6]),
        )

    def insert_in_flight(
        self, client_order_id: str, kind: str, target: str, request: dict[str, Any]
    ) -> bool:
        """Atomically create an IN_FLIGHT record. ``False`` if one already exists."""
        now = time.time()
        with self._lock:
            try:
                self._db.execute(
                    "INSERT INTO order_journal (client_order_id, kind, target, state,"
                    " request_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (client_order_id, kind, target, IN_FLIGHT, json.dumps(request), now, now),
                )
            except sqlite3.IntegrityError:
                return False
        return True

    def mark_done(self, client_order_id: str, status_code: int, response: dict[str, Any]) -> None:
        self._update(client_order_id, DONE, status_code, json.dumps(response))

    def mark_unknown(self, client_order_id: str) -> None:
        self._update(client_order_id, UNKNOWN, None, None)

    def _update(self, coid: str, state: str, status: int | None, resp: str | None) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE order_journal SET state = ?, status_code = ?, response_json = ?,"
                " updated_at = ? WHERE client_order_id = ?",
                (state, status, resp, time.time(), coid),
            )

    def delete(self, client_order_id: str) -> None:
        with self._lock:
            self._db.execute(
                "DELETE FROM order_journal WHERE client_order_id = ?", (client_order_id,)
            )

    # -- meta (persisted server offset) -------------------------------------------
    def get_meta(self, key: str) -> str | None:
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else str(row[0])

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?)"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
