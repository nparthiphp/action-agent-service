from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from action_agent.core.audit import AuditLog
from action_agent.core.autonomy import Mode
from action_agent.core.catalog import default_catalog
from action_agent.core.hub import ExecutorClient, ExecutorHub, InProcessExecutorClient
from action_agent.core.models import Recommendation, StepSpec
from action_agent.core.orchestrator import Orchestrator
from action_agent.core.policy import StubPolicyClient
from action_agent.core.store import Store
from action_agent.core.verifier import StubHealthSource, Verifier
from action_agent.executors.finops.app import FinOpsExecutor
from action_agent.executors.incident.app import IncidentExecutor
from action_agent.executors.infra.app import InfraExecutor


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: int) -> None:
        self.now += timedelta(**kwargs)


@dataclass
class Env:
    orch: Orchestrator
    store: Store
    audit: AuditLog
    clock: FakeClock
    incident: IncidentExecutor
    infra: InfraExecutor
    finops: FinOpsExecutor
    health: StubHealthSource


def make_env(
    *,
    default_mode: Mode = Mode.AUTO_T1,
    modes: dict[str, Mode] | None = None,
    policy: Any = None,
    unhealthy: tuple[str, ...] = (),
    wrap: Any = None,
    ttl_minutes: int = 30,
) -> Env:
    clock = FakeClock()
    store = Store(":memory:")
    audit = AuditLog(store, clock)
    incident, infra, finops = IncidentExecutor(), InfraExecutor(), FinOpsExecutor()
    clients: dict[str, ExecutorClient] = {
        "incident": InProcessExecutorClient(incident),
        "infra": InProcessExecutorClient(infra),
        "finops": InProcessExecutorClient(finops),
    }
    if wrap is not None:
        clients = {domain: wrap(domain, client) for domain, client in clients.items()}
    health = StubHealthSource(unhealthy)
    orch = Orchestrator(
        catalog=default_catalog(),
        store=store,
        audit=audit,
        policy=policy or StubPolicyClient(),
        hub=ExecutorHub(clients, max_attempts=3, backoff_s=0, sleep=lambda _s: None),
        verifier=Verifier(health),
        modes=modes,
        default_mode=default_mode,
        approval_ttl=timedelta(minutes=ttl_minutes),
        clock=clock,
    )
    return Env(orch, store, audit, clock, incident, infra, finops, health)


def rec(
    steps: list[tuple[str, dict[str, Any]]],
    *,
    rec_id: str = "rec-1",
    target: str = "payments",
    environment: str = "nonprod",
    confidence: float = 0.9,
) -> Recommendation:
    return Recommendation(
        recommendation_id=rec_id,
        target=target,
        environment=environment,  # type: ignore[arg-type]
        steps=[StepSpec(action_id=a, params=p) for a, p in steps],
        confidence=confidence,
        rationale="test",
    )


TICKET = ("create_ticket", {"title": "Payments failing", "severity": "high", "service": "payments"})
