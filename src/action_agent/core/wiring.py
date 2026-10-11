"""Builds a ready orchestrator from settings."""
from __future__ import annotations

import logging
from datetime import timedelta

from action_agent.executors.finops.app import FinOpsExecutor
from action_agent.executors.incident.app import IncidentExecutor
from action_agent.executors.infra.app import InfraExecutor

from .audit import AuditLog
from .catalog import default_catalog
from .config import Settings
from .hub import ExecutorClient, ExecutorHub, HttpExecutorClient, InProcessExecutorClient
from .models import now_utc
from .orchestrator import Orchestrator
from .policy import HttpPolicyClient, PolicyClient, StubPolicyClient
from .store import Store
from .verifier import HealthSource, HttpHealthSource, StubHealthSource, Verifier

log = logging.getLogger("action_agent")

_IN_PROCESS = {"incident": IncidentExecutor, "infra": InfraExecutor, "finops": FinOpsExecutor}


def build_orchestrator(settings: Settings) -> Orchestrator:
    store = Store(settings.db_path)
    audit = AuditLog(store, now_utc)

    policy: PolicyClient
    if settings.policy_url:
        policy = HttpPolicyClient(settings.policy_url)
    else:
        log.warning("AA_POLICY_URL is not set: using the local stub policy client, not the Policy Agent")
        policy = StubPolicyClient()

    health: HealthSource
    if settings.health_url:
        health = HttpHealthSource(settings.health_url)
    else:
        log.warning("AA_HEALTH_URL is not set: using the local stub health source, not ARIES monitoring")
        health = StubHealthSource()

    clients: dict[str, ExecutorClient] = {}
    for domain, factory in _IN_PROCESS.items():
        url = settings.executor_urls.get(domain)
        if url:
            clients[domain] = HttpExecutorClient(url)
        else:
            log.warning("no executor URL for '%s': running the simulated executor in-process", domain)
            clients[domain] = InProcessExecutorClient(factory())

    return Orchestrator(
        catalog=default_catalog(),
        store=store,
        audit=audit,
        policy=policy,
        hub=ExecutorHub(clients),
        verifier=Verifier(health),
        modes=settings.modes,
        default_mode=settings.default_mode,
        approval_ttl=timedelta(minutes=settings.approval_ttl_minutes),
    )
