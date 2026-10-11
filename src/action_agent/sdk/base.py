"""Executor SDK: the handler interface, idempotency, and the HTTP app every executor exposes."""
from __future__ import annotations

import threading
from typing import Any, Callable, Iterable

from fastapi import FastAPI, HTTPException

from .models import ExecRequest, ExecResult, RollbackRequest


class ActionHandler:
    """One action implemented against one target system (a connector call).

    Subclasses set ``action_id`` and implement ``execute``. Implement ``rollback`` for every
    action whose catalog contract declares a rollback other than "none".
    """

    action_id: str = ""

    def dry_run(self, params: dict[str, Any]) -> ExecResult:
        return ExecResult(ok=True, detail="dry-run: no change made")

    def execute(self, params: dict[str, Any]) -> ExecResult:
        raise NotImplementedError

    def rollback(self, params: dict[str, Any], token: dict[str, Any] | None) -> ExecResult:
        raise NotImplementedError


class BaseExecutor:
    """Holds the handlers for one domain and guarantees idempotent execute and rollback."""

    def __init__(self, domain: str, handlers: Iterable[ActionHandler]) -> None:
        self.domain = domain
        self._handlers = {h.action_id: h for h in handlers}
        self._results: dict[str, ExecResult] = {}
        self._lock = threading.Lock()

    @property
    def action_ids(self) -> list[str]:
        return sorted(self._handlers)

    def _handler(self, action_id: str) -> ActionHandler:
        handler = self._handlers.get(action_id)
        if handler is None:
            raise KeyError(action_id)
        return handler

    @staticmethod
    def _safe(fn: Callable[[], ExecResult]) -> ExecResult:
        try:
            return fn()
        except KeyError as exc:
            return ExecResult(ok=False, detail=f"unknown or missing value {exc}")
        except Exception as exc:  # a connector failure must never crash the executor
            return ExecResult(ok=False, detail=f"{type(exc).__name__}: {exc}")

    def dry_run(self, req: ExecRequest) -> ExecResult:
        handler = self._handler(req.action_id)
        return self._safe(lambda: handler.dry_run(req.params))

    def execute(self, req: ExecRequest) -> ExecResult:
        handler = self._handler(req.action_id)
        with self._lock:
            cached = self._results.get(req.idempotency_key)
            if cached is not None:
                return cached.model_copy(update={"replayed": True})
            result = self._safe(lambda: handler.execute(req.params))
            self._results[req.idempotency_key] = result
            return result

    def rollback(self, req: RollbackRequest) -> ExecResult:
        handler = self._handler(req.action_id)
        key = f"rollback:{req.idempotency_key}"
        with self._lock:
            cached = self._results.get(key)
            if cached is not None:
                return cached.model_copy(update={"replayed": True})
            result = self._safe(lambda: handler.rollback(req.params, req.rollback_token))
            self._results[key] = result
            return result


def create_executor_app(executor: BaseExecutor) -> FastAPI:
    app = FastAPI(title=f"Action Agent executor: {executor.domain}")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "domain": executor.domain}

    @app.get("/actions")
    def actions() -> dict[str, Any]:
        return {"domain": executor.domain, "actions": executor.action_ids}

    def _call(fn: Callable[[Any], ExecResult], req: Any) -> ExecResult:
        try:
            return fn(req)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"unknown action: {req.action_id}")

    @app.post("/dry-run", response_model=ExecResult)
    def dry_run(req: ExecRequest) -> ExecResult:
        return _call(executor.dry_run, req)

    @app.post("/execute", response_model=ExecResult)
    def execute(req: ExecRequest) -> ExecResult:
        return _call(executor.execute, req)

    @app.post("/rollback", response_model=ExecResult)
    def rollback(req: RollbackRequest) -> ExecResult:
        return _call(executor.rollback, req)

    return app
