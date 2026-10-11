"""Wire models shared by the core service and every executor."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ExecRequest(BaseModel):
    run_id: str
    step_id: str
    action_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    # Same key on every retry of the same step, so a retry can never apply a change twice.
    idempotency_key: str
    dry_run: bool = False


class ExecResult(BaseModel):
    ok: bool
    detail: str = ""
    output: dict[str, Any] = Field(default_factory=dict)
    # Whatever the executor needs to undo this step later. Opaque to the core.
    rollback_token: dict[str, Any] | None = None
    # True when the idempotency key had already been executed and the stored result is returned.
    replayed: bool = False


class RollbackRequest(BaseModel):
    run_id: str
    step_id: str
    action_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    rollback_token: dict[str, Any] | None = None
    idempotency_key: str
