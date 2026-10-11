"""Policy check. The Policy Agent is a separate shared service; the core holds no rules of its own.

``HttpPolicyClient`` assumes a ``POST /v1/evaluate`` endpoint with the request and response shapes
below. That shape is an ASSUMPTION to be aligned with the real Policy Agent API. Any failure to get
an answer is treated as a denial (fail closed).
"""
from __future__ import annotations

from typing import Any, Iterable, Protocol

import httpx
from pydantic import BaseModel, Field

from .models import PolicyDecision


class PolicyRequest(BaseModel):
    run_id: str
    target: str
    environment: str
    tier: str
    confidence: float
    source: str
    action_ids: list[str]
    steps: list[dict[str, Any]] = Field(default_factory=list)


class PolicyClient(Protocol):
    def evaluate(self, req: PolicyRequest) -> PolicyDecision: ...


class StubPolicyClient:
    """Local stand-in for development and tests. It is not a policy engine."""

    def __init__(self, protected_targets: Iterable[str] = (), blocked_actions: Iterable[str] = ()) -> None:
        self.protected_targets = set(protected_targets)
        self.blocked_actions = set(blocked_actions)

    def evaluate(self, req: PolicyRequest) -> PolicyDecision:
        if req.target in self.protected_targets:
            return PolicyDecision(allowed=False, reason=f"target '{req.target}' is protected", policy_id="stub")
        blocked = [a for a in req.action_ids if a in self.blocked_actions]
        if blocked:
            return PolicyDecision(allowed=False, reason=f"actions blocked by policy: {blocked}", policy_id="stub")
        return PolicyDecision(allowed=True, reason="stub policy: no rule matched", policy_id="stub")


class HttpPolicyClient:
    def __init__(self, base_url: str, client: httpx.Client | None = None, timeout: float = 5.0) -> None:
        self._client = client or httpx.Client(base_url=base_url, timeout=timeout)

    def evaluate(self, req: PolicyRequest) -> PolicyDecision:
        try:
            response = self._client.post("/v1/evaluate", json=req.model_dump())
            response.raise_for_status()
            return PolicyDecision.model_validate(response.json())
        except Exception as exc:
            return PolicyDecision(
                allowed=False,
                reason=f"policy service unavailable ({type(exc).__name__}); denied (fail closed)",
            )
