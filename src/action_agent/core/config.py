"""Settings from environment variables.

AA_DB_PATH               SQLite file (default data/action_agent.db)
AA_DEFAULT_MODE          shadow | suggest | approve_and_run | auto_t1 (default approve_and_run)
AA_MODES                 per action overrides, e.g. "restart_service=auto_t1,create_ticket=auto_t1"
AA_APPROVAL_TTL_MIN      minutes an approval stays open (default 30)
AA_POLICY_URL            Policy Agent base URL; unset uses the local stub
AA_HEALTH_URL            ARIES monitoring base URL; unset uses the local stub
AA_EXECUTOR_<DOMAIN>_URL executor base URL for INCIDENT, INFRA, FINOPS; unset runs it in-process
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

from .autonomy import Mode

DOMAINS = ("incident", "infra", "finops")


@dataclass(frozen=True)
class Settings:
    db_path: str = "data/action_agent.db"
    default_mode: Mode = Mode.APPROVE_AND_RUN
    modes: dict[str, Mode] = field(default_factory=dict)
    approval_ttl_minutes: int = 30
    policy_url: str | None = None
    health_url: str | None = None
    executor_urls: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ) if env is None else env
        modes: dict[str, Mode] = {}
        for pair in filter(None, (p.strip() for p in env.get("AA_MODES", "").split(","))):
            action_id, _, mode = pair.partition("=")
            modes[action_id.strip()] = Mode(mode.strip())
        return cls(
            db_path=env.get("AA_DB_PATH", "data/action_agent.db"),
            default_mode=Mode(env.get("AA_DEFAULT_MODE", Mode.APPROVE_AND_RUN.value)),
            modes=modes,
            approval_ttl_minutes=int(env.get("AA_APPROVAL_TTL_MIN", "30")),
            policy_url=env.get("AA_POLICY_URL") or None,
            health_url=env.get("AA_HEALTH_URL") or None,
            executor_urls={
                d: env[f"AA_EXECUTOR_{d.upper()}_URL"] for d in DOMAINS if env.get(f"AA_EXECUTOR_{d.upper()}_URL")
            },
        )
