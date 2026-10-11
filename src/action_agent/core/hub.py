"""Executor hub: routes each step to the executor for its domain, with bounded retries."""
from __future__ import annotations

import time
from typing import Callable, Mapping, Protocol

import httpx

from action_agent.sdk import BaseExecutor, ExecRequest, ExecResult, RollbackRequest


class ExecutorUnavailable(Exception):
    """A transient failure: the executor could not be reached or answered with a server error."""


class ExecutorClient(Protocol):
    def dry_run(self, req: ExecRequest) -> ExecResult: ...
    def execute(self, req: ExecRequest) -> ExecResult: ...
    def rollback(self, req: RollbackRequest) -> ExecResult: ...


class InProcessExecutorClient:
    """Calls an executor object directly. For development and tests."""

    def __init__(self, executor: BaseExecutor) -> None:
        self.executor = executor

    def dry_run(self, req: ExecRequest) -> ExecResult:
        return self.executor.dry_run(req)

    def execute(self, req: ExecRequest) -> ExecResult:
        return self.executor.execute(req)

    def rollback(self, req: RollbackRequest) -> ExecResult:
        return self.executor.rollback(req)


class HttpExecutorClient:
    def __init__(self, base_url: str, client: httpx.Client | None = None, timeout: float = 10.0) -> None:
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout)

    def _post(self, path: str, body: dict) -> ExecResult:
        try:
            response = self._client.post(path, json=body)
        except httpx.TransportError as exc:
            raise ExecutorUnavailable(str(exc)) from exc
        if response.status_code >= 500:
            raise ExecutorUnavailable(f"HTTP {response.status_code}")
        if response.status_code >= 400:
            return ExecResult(ok=False, detail=f"executor rejected the request: HTTP {response.status_code}")
        return ExecResult.model_validate(response.json())

    def dry_run(self, req: ExecRequest) -> ExecResult:
        return self._post("/dry-run", req.model_dump())

    def execute(self, req: ExecRequest) -> ExecResult:
        return self._post("/execute", req.model_dump())

    def rollback(self, req: RollbackRequest) -> ExecResult:
        return self._post("/rollback", req.model_dump())


class ExecutorHub:
    def __init__(
        self,
        clients: Mapping[str, ExecutorClient],
        max_attempts: int = 3,
        backoff_s: float = 0.2,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._clients = dict(clients)
        self._max_attempts = max_attempts
        self._backoff_s = backoff_s
        self._sleep = sleep

    def domains(self) -> list[str]:
        return sorted(self._clients)

    def _call(self, domain: str, method: str, req) -> tuple[ExecResult, int]:
        client = self._clients.get(domain)
        if client is None:
            return ExecResult(ok=False, detail=f"no executor registered for domain '{domain}'"), 0
        attempts = 0
        while True:
            attempts += 1
            try:
                return getattr(client, method)(req), attempts
            except ExecutorUnavailable as exc:
                if attempts >= self._max_attempts:
                    return (
                        ExecResult(ok=False, detail=f"executor unavailable after {attempts} attempts: {exc}"),
                        attempts,
                    )
                self._sleep(self._backoff_s * 2 ** (attempts - 1))

    def dry_run(self, domain: str, req: ExecRequest) -> tuple[ExecResult, int]:
        return self._call(domain, "dry_run", req)

    def execute(self, domain: str, req: ExecRequest) -> tuple[ExecResult, int]:
        return self._call(domain, "execute", req)

    def rollback(self, domain: str, req: RollbackRequest) -> tuple[ExecResult, int]:
        return self._call(domain, "rollback", req)
