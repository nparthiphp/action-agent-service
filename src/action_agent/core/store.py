"""SQLite persistence for runs, the audit chain and flags (the kill switch)."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from .models import ActionRun

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    rec_id TEXT NOT NULL UNIQUE,
    body   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit (
    seq       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    run_id    TEXT NOT NULL,
    event     TEXT NOT NULL,
    data      TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash      TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS flags (
    name  TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str = ":memory:") -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.RLock()
        with self.lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # ---- runs --------------------------------------------------------------------------------
    def save_run(self, run: ActionRun) -> None:
        with self.lock:
            self._conn.execute(
                "INSERT INTO runs(run_id, rec_id, body) VALUES (?, ?, ?) "
                "ON CONFLICT(run_id) DO UPDATE SET body = excluded.body",
                (run.run_id, run.recommendation.recommendation_id, run.model_dump_json()),
            )
            self._conn.commit()

    def get_run(self, run_id: str) -> ActionRun | None:
        with self.lock:
            row = self._conn.execute("SELECT body FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return ActionRun.model_validate_json(row[0]) if row else None

    def find_by_recommendation(self, recommendation_id: str) -> ActionRun | None:
        with self.lock:
            row = self._conn.execute("SELECT body FROM runs WHERE rec_id = ?", (recommendation_id,)).fetchone()
        return ActionRun.model_validate_json(row[0]) if row else None

    def list_runs(self, limit: int = 50) -> list[ActionRun]:
        with self.lock:
            rows = self._conn.execute("SELECT body FROM runs ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
        return [ActionRun.model_validate_json(r[0]) for r in rows]

    # ---- flags -------------------------------------------------------------------------------
    def get_flag(self, name: str) -> str | None:
        with self.lock:
            row = self._conn.execute("SELECT value FROM flags WHERE name = ?", (name,)).fetchone()
        return row[0] if row else None

    def set_flag(self, name: str, value: str) -> None:
        with self.lock:
            self._conn.execute(
                "INSERT INTO flags(name, value) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET value = excluded.value",
                (name, value),
            )
            self._conn.commit()

    # ---- audit rows (hash chaining lives in audit.py) --------------------------------------
    def last_audit_hash(self) -> str | None:
        row = self._conn.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        return row[0] if row else None

    def append_audit(self, ts: str, run_id: str, event: str, data: str, prev_hash: str, hash_: str) -> None:
        self._conn.execute(
            "INSERT INTO audit(ts, run_id, event, data, prev_hash, hash) VALUES (?, ?, ?, ?, ?, ?)",
            (ts, run_id, event, data, prev_hash, hash_),
        )
        self._conn.commit()

    def audit_rows(self, run_id: str | None = None) -> list[tuple]:
        with self.lock:
            if run_id is None:
                cur = self._conn.execute(
                    "SELECT seq, ts, run_id, event, data, prev_hash, hash FROM audit ORDER BY seq"
                )
            else:
                cur = self._conn.execute(
                    "SELECT seq, ts, run_id, event, data, prev_hash, hash FROM audit WHERE run_id = ? ORDER BY seq",
                    (run_id,),
                )
            return cur.fetchall()
