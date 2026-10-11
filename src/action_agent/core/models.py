"""Core data models: the action contract, recommendations, and the run record."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum, IntEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, Field, PlainSerializer, model_validator


class Tier(IntEnum):
    T0 = 0  # read only
    T1 = 1  # reversible, low blast radius
    T2 = 2  # impactful or hard to undo
    T3 = 3  # critical or irreversible: people execute, the agent prepares


def _coerce_tier(value: Any) -> Any:
    return Tier[value] if isinstance(value, str) else value


# Serialises as "T1" in JSON and the database, accepts "T1" or 1 on the way in.
TierT = Annotated[Tier, BeforeValidator(_coerce_tier), PlainSerializer(lambda t: t.name, return_type=str)]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class RollbackKind(str, Enum):
    REVERT = "revert"  # the change is undone exactly
    COMPENSATE = "compensate"  # the change cannot be undone, a compensating action limits the damage
    NONE = "none"  # nothing to undo (read-only or a notification); only allowed up to T1


class RunStatus(str, Enum):
    RECEIVED = "received"
    INVALID = "invalid"
    REJECTED_BY_POLICY = "rejected_by_policy"
    SHADOWED = "shadowed"  # shadow mode: planned and recorded, nothing executed
    AWAITING_HUMAN = "awaiting_human"  # suggest mode: a person carries out the plan
    HUMAN_REQUIRED = "human_required"  # T3: a person must execute, the agent prepared the plan
    AWAITING_APPROVAL = "awaiting_approval"
    DENIED = "denied"
    EXPIRED = "expired"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"
    FAILED = "failed"
    KILLED = "killed"


class StepSpec(BaseModel):
    action_id: str
    # A value of the form "$step[0].ticket_id" takes that output field from an earlier step.
    params: dict[str, Any] = Field(default_factory=dict)


class Recommendation(BaseModel):
    recommendation_id: str = Field(min_length=1)
    target: str = Field(min_length=1)
    environment: Literal["prod", "nonprod"]
    steps: list[StepSpec] = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)
    rationale: str = ""
    source: str = "aries"
    incident_ref: str | None = None


class VerifySpec(BaseModel):
    check: str = Field(min_length=1)
    description: str = Field(min_length=1)


class RollbackSpec(BaseModel):
    kind: RollbackKind
    description: str = Field(min_length=1)


class ActionContract(BaseModel):
    action_id: str
    domain: str
    summary: str
    version: str = "1.0.0"
    inputs: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    blast_radius: str
    tier: TierT
    # Minimum tier when the target environment is production.
    production_floor: TierT | None = None
    # When params[blast_param] exceeds blast_limit the tier goes up one level.
    blast_param: str | None = None
    blast_limit: float | None = None
    verify: VerifySpec
    rollback: RollbackSpec

    @model_validator(mode="after")
    def _check(self) -> "ActionContract":
        if self.rollback.kind is RollbackKind.NONE and self.tier >= Tier.T2:
            raise ValueError(f"{self.action_id}: rollback 'none' is only allowed up to T1")
        if (self.blast_param is None) != (self.blast_limit is None):
            raise ValueError(f"{self.action_id}: blast_param and blast_limit go together")
        return self


class StepRecord(BaseModel):
    index: int
    action_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    status: Literal[
        "pending",
        "dry_run_ok",
        "executed",
        "verified",
        "failed",
        "rolled_back",
        "rollback_skipped",
        "rollback_failed",
    ] = "pending"
    detail: str = ""
    attempts: int = 0
    output: dict[str, Any] = Field(default_factory=dict)
    rollback_token: dict[str, Any] | None = None


class ApprovalRecord(BaseModel):
    requested_at: datetime
    expires_at: datetime
    status: Literal["pending", "approved", "denied", "expired"] = "pending"
    decided_by: str | None = None
    decided_at: datetime | None = None
    comment: str = ""


class PolicyDecision(BaseModel):
    allowed: bool
    reason: str = ""
    requires_approval: bool = False
    policy_id: str | None = None


def new_run_id() -> str:
    return f"run-{uuid.uuid4().hex[:12]}"


class ActionRun(BaseModel):
    run_id: str = Field(default_factory=new_run_id)
    recommendation: Recommendation
    status: RunStatus = RunStatus.RECEIVED
    tier: TierT | None = None
    mode: str | None = None
    risk_reasons: list[str] = Field(default_factory=list)
    policy: PolicyDecision | None = None
    approval: ApprovalRecord | None = None
    steps: list[StepRecord] = Field(default_factory=list)
    # For T3, suggest mode and shadow mode: what a person would do, with verify and rollback.
    human_plan: list[dict[str, Any]] | None = None
    needs_escalation: bool = False
    message: str = ""
    created_at: datetime = Field(default_factory=now_utc)
    updated_at: datetime = Field(default_factory=now_utc)
