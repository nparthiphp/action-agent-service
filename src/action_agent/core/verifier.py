"""Verifier: confirms a change worked. Health comes from ARIES monitoring, not from a second monitor.

``HttpHealthSource`` assumes a ``POST /v1/health-check`` endpoint. That shape is an ASSUMPTION to be
aligned with the real ARIES monitoring API. A failed or unreachable check counts as not verified, so
the change is rolled back (fail closed).
"""
from __future__ import annotations

from typing import Any, Iterable, Protocol

import httpx
from pydantic import BaseModel

from action_agent.sdk import ExecResult

from .models import VerifySpec


class VerifyResult(BaseModel):
    ok: bool
    detail: str = ""


class HealthSource(Protocol):
    def check(self, check: str, target: str, params: dict[str, Any]) -> VerifyResult: ...


class StubHealthSource:
    """Local stand-in: everything is healthy unless the target is listed as unhealthy."""

    def __init__(self, unhealthy_targets: Iterable[str] = ()) -> None:
        self.unhealthy_targets = set(unhealthy_targets)

    def check(self, check: str, target: str, params: dict[str, Any]) -> VerifyResult:
        if target in self.unhealthy_targets:
            return VerifyResult(ok=False, detail=f"{check}: {target} is unhealthy")
        return VerifyResult(ok=True, detail=f"{check}: {target} is healthy")


class HttpHealthSource:
    def __init__(self, base_url: str, client: httpx.Client | None = None, timeout: float = 5.0) -> None:
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout)

    def check(self, check: str, target: str, params: dict[str, Any]) -> VerifyResult:
        try:
            response = self._client.post(
                "/v1/health-check", json={"check": check, "target": target, "params": params}
            )
            response.raise_for_status()
            return VerifyResult.model_validate(response.json())
        except Exception as exc:
            return VerifyResult(ok=False, detail=f"health source unavailable ({type(exc).__name__})")


class Verifier:
    def __init__(self, health: HealthSource) -> None:
        self._health = health

    def verify(self, spec: VerifySpec, target: str, params: dict[str, Any], result: ExecResult) -> VerifyResult:
        if spec.check == "executor_confirmed":
            return VerifyResult(ok=result.ok, detail="executor confirmed the change")
        try:
            return self._health.check(spec.check, target, params)
        except Exception as exc:
            return VerifyResult(ok=False, detail=f"health check error ({type(exc).__name__}); not verified")
