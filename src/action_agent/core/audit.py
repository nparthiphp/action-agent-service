"""Append-only audit trail. Each entry hashes the one before it, so edits or deletions are detectable.

The chain detects tampering after the fact. It does not prevent it: anyone who can rewrite the whole
table can rebuild the chain. For real use, ship entries to write-once storage as well.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Callable

from .store import Store

GENESIS = "0" * 64


def _digest(prev: str, ts: str, run_id: str, event: str, data: str) -> str:
    return hashlib.sha256(f"{prev}|{ts}|{run_id}|{event}|{data}".encode()).hexdigest()


class AuditLog:
    def __init__(self, store: Store, clock: Callable[[], datetime]) -> None:
        self._store = store
        self._clock = clock

    def record(self, run_id: str, event: str, **data: Any) -> None:
        with self._store.lock:
            prev = self._store.last_audit_hash() or GENESIS
            ts = self._clock().isoformat()
            payload = json.dumps(data, sort_keys=True, default=str)
            self._store.append_audit(ts, run_id, event, payload, prev, _digest(prev, ts, run_id, event, payload))

    def entries(self, run_id: str | None = None) -> list[dict[str, Any]]:
        return [
            {"seq": seq, "ts": ts, "run_id": rid, "event": event, "data": json.loads(data), "hash": h}
            for seq, ts, rid, event, data, _prev, h in self._store.audit_rows(run_id)
        ]

    def verify(self) -> tuple[bool, int | None]:
        """Returns (True, None) when the chain is intact, else (False, seq of the first bad entry)."""
        prev = GENESIS
        for seq, ts, run_id, event, data, prev_hash, hash_ in self._store.audit_rows():
            if prev_hash != prev or hash_ != _digest(prev, ts, run_id, event, data):
                return False, seq
            prev = hash_
        return True, None
