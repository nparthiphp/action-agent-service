"""Approval handling for T2 plans (and any plan the policy says needs a person)."""
from __future__ import annotations

from datetime import datetime, timedelta

from .models import ActionRun, ApprovalRecord


class ApprovalService:
    def __init__(self, ttl: timedelta) -> None:
        self.ttl = ttl

    def open(self, run: ActionRun, now: datetime) -> None:
        run.approval = ApprovalRecord(requested_at=now, expires_at=now + self.ttl)

    @staticmethod
    def is_expired(run: ActionRun, now: datetime) -> bool:
        return run.approval is not None and now > run.approval.expires_at

    @staticmethod
    def expire(run: ActionRun) -> None:
        if run.approval is not None:
            run.approval.status = "expired"

    @staticmethod
    def decide(run: ActionRun, approver: str, approved: bool, comment: str, now: datetime) -> None:
        assert run.approval is not None
        run.approval.status = "approved" if approved else "denied"
        run.approval.decided_by = approver
        run.approval.decided_at = now
        run.approval.comment = comment
