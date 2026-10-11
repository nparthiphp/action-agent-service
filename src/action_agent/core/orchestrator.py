"""Orchestrator: runs a recommendation through every control, in order, and never skips one.

Flow: validate, kill switch, risk tier, policy check, trust-ladder decision, then (when allowed)
approval, dry run of every step, execute each step with verification, and roll back on failure.

This build runs a plan synchronously inside the request, guarded by one lock. That is fine for a
pilot and wrong for scale: the next step is to move execution onto a queue with a durable workflow
engine, keeping the same state machine and the same run record.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any, Callable, Mapping

from action_agent.sdk import ExecRequest, RollbackRequest

from .approvals import ApprovalService
from .audit import AuditLog
from .autonomy import Disposition, Mode, decide, effective_mode
from .catalog import Catalog
from .hub import ExecutorHub
from .models import (
    ActionRun,
    PolicyDecision,
    Recommendation,
    RollbackKind,
    RunStatus,
    StepRecord,
    Tier,
    now_utc,
)
from .planner import PLACEHOLDER, PassthroughPlanner, Planner, validate_plan
from .policy import PolicyClient, PolicyRequest
from .risk import assess
from .store import Store
from .verifier import Verifier

KILL_SWITCH = "kill_switch"


class RunNotFound(Exception):
    pass


class InvalidState(Exception):
    pass


class PlanError(Exception):
    pass


class Orchestrator:
    def __init__(
        self,
        *,
        catalog: Catalog,
        store: Store,
        audit: AuditLog,
        policy: PolicyClient,
        hub: ExecutorHub,
        verifier: Verifier,
        planner: Planner | None = None,
        modes: Mapping[str, Mode] | None = None,
        default_mode: Mode = Mode.APPROVE_AND_RUN,
        approval_ttl: timedelta = timedelta(minutes=30),
        clock: Callable[[], datetime] = now_utc,
        escalate: Callable[[ActionRun, str], None] | None = None,
    ) -> None:
        self._catalog = catalog
        self._store = store
        self._audit = audit
        self._policy = policy
        self._hub = hub
        self._verifier = verifier
        self._planner = planner or PassthroughPlanner()
        self._modes = dict(modes or {})
        self._default_mode = default_mode
        self._approvals = ApprovalService(approval_ttl)
        self._clock = clock
        self._escalate_hook = escalate
        self._lock = threading.RLock()

    # ---- read side ---------------------------------------------------------------------------
    @property
    def catalog(self) -> Catalog:
        return self._catalog

    @property
    def audit(self) -> AuditLog:
        return self._audit

    def get_run(self, run_id: str) -> ActionRun:
        run = self._store.get_run(run_id)
        if run is None:
            raise RunNotFound(run_id)
        return run

    def list_runs(self, limit: int = 50) -> list[ActionRun]:
        return self._store.list_runs(limit)

    # ---- kill switch -------------------------------------------------------------------------
    def kill_switch_engaged(self) -> bool:
        return self._store.get_flag(KILL_SWITCH) == "1"

    def set_kill_switch(self, engaged: bool, by: str) -> None:
        with self._lock:
            self._store.set_flag(KILL_SWITCH, "1" if engaged else "0")
            self._audit.record("system", "kill_switch", engaged=engaged, by=by)

    # ---- write side --------------------------------------------------------------------------
    def submit(self, rec: Recommendation) -> tuple[ActionRun, bool]:
        """Returns the run and whether it is new. A repeated recommendation id returns the same run."""
        with self._lock:
            existing = self._store.find_by_recommendation(rec.recommendation_id)
            if existing is not None:
                self._audit.record(
                    existing.run_id, "duplicate_recommendation", recommendation_id=rec.recommendation_id
                )
                return existing, False

            run = ActionRun(recommendation=rec, created_at=self._clock(), updated_at=self._clock())
            self._save(run)
            self._audit.record(
                run.run_id,
                "received",
                recommendation_id=rec.recommendation_id,
                target=rec.target,
                environment=rec.environment,
                source=rec.source,
                steps=[s.action_id for s in rec.steps],
            )

            rec = self._planner.plan(rec)
            run.recommendation = rec
            errors = validate_plan(rec, self._catalog)
            if errors:
                return self._finish(run, RunStatus.INVALID, "; ".join(errors)), True

            if self.kill_switch_engaged():
                return self._finish(run, RunStatus.KILLED, "kill switch engaged; nothing executed"), True

            risk = assess(rec, self._catalog)
            run.tier = risk.tier
            run.risk_reasons = risk.reasons

            decision = self._evaluate_policy(run)
            run.policy = decision
            if not decision.allowed:
                return self._finish(run, RunStatus.REJECTED_BY_POLICY, decision.reason), True

            mode = effective_mode(self._modes, self._default_mode, [s.action_id for s in rec.steps])
            run.mode = mode.value
            disposition = decide(risk.tier, mode)
            if disposition is Disposition.AUTO and decision.requires_approval:
                disposition = Disposition.NEEDS_APPROVAL
            self._audit.record(
                run.run_id,
                "risk_and_mode",
                tier=risk.tier.name,
                mode=mode.value,
                disposition=disposition.value,
                reasons=risk.reasons,
            )

            if disposition is Disposition.SHADOW_ONLY:
                run.human_plan = self._human_plan(run)
                return self._finish(run, RunStatus.SHADOWED, "shadow mode: planned and recorded, nothing executed"), True
            if disposition is Disposition.HUMAN_EXECUTES:
                run.human_plan = self._human_plan(run)
                if risk.tier >= Tier.T3:
                    msg = "T3: a person must execute this plan; the agent has prepared it"
                    return self._finish(run, RunStatus.HUMAN_REQUIRED, msg), True
                msg = "suggest mode: a person carries out this plan"
                return self._finish(run, RunStatus.AWAITING_HUMAN, msg), True
            if disposition is Disposition.NEEDS_APPROVAL:
                self._approvals.open(run, self._clock())
                return self._finish(run, RunStatus.AWAITING_APPROVAL, "waiting for approval"), True

            return self._execute(run), True

    def approve(self, run_id: str, approver: str, comment: str = "") -> ActionRun:
        return self._decide(run_id, approver, True, comment)

    def deny(self, run_id: str, approver: str, comment: str = "") -> ActionRun:
        return self._decide(run_id, approver, False, comment)

    # ---- internals ---------------------------------------------------------------------------
    def _decide(self, run_id: str, approver: str, approved: bool, comment: str) -> ActionRun:
        with self._lock:
            run = self.get_run(run_id)
            if run.status is not RunStatus.AWAITING_APPROVAL:
                raise InvalidState(f"run is {run.status.value}, not awaiting approval")
            if not approver.strip():
                raise ValueError("approver is required")
            now = self._clock()
            if self._approvals.is_expired(run, now):
                self._approvals.expire(run)
                return self._finish(run, RunStatus.EXPIRED, "approval expired; nothing executed")
            self._approvals.decide(run, approver, approved, comment, now)
            self._audit.record(
                run.run_id, "approved" if approved else "denied", by=approver, comment=comment
            )
            if not approved:
                return self._finish(run, RunStatus.DENIED, f"denied by {approver}")
            if self.kill_switch_engaged():
                return self._finish(run, RunStatus.KILLED, "kill switch engaged; nothing executed")
            decision = self._evaluate_policy(run)  # policy is checked again at execution time
            run.policy = decision
            if not decision.allowed:
                return self._finish(run, RunStatus.REJECTED_BY_POLICY, decision.reason)
            return self._execute(run)

    def _evaluate_policy(self, run: ActionRun) -> PolicyDecision:
        rec = run.recommendation
        assert run.tier is not None
        req = PolicyRequest(
            run_id=run.run_id,
            target=rec.target,
            environment=rec.environment,
            tier=run.tier.name,
            confidence=rec.confidence,
            source=rec.source,
            action_ids=[s.action_id for s in rec.steps],
            steps=[s.model_dump() for s in rec.steps],
        )
        try:
            decision = self._policy.evaluate(req)
        except Exception as exc:
            decision = PolicyDecision(
                allowed=False, reason=f"policy check failed ({type(exc).__name__}); denied (fail closed)"
            )
        self._audit.record(
            run.run_id,
            "policy_decision",
            allowed=decision.allowed,
            reason=decision.reason,
            requires_approval=decision.requires_approval,
            policy_id=decision.policy_id,
        )
        return decision

    def _human_plan(self, run: ActionRun) -> list[dict[str, Any]]:
        plan = []
        for index, step in enumerate(run.recommendation.steps):
            contract = self._catalog.require(step.action_id)
            plan.append(
                {
                    "step": index,
                    "action_id": contract.action_id,
                    "summary": contract.summary,
                    "params": step.params,
                    "preconditions": contract.preconditions,
                    "verify": contract.verify.description,
                    "rollback": f"{contract.rollback.kind.value}: {contract.rollback.description}",
                }
            )
        return plan

    @staticmethod
    def _resolve(params: dict[str, Any], steps: list[StepRecord], dry: bool) -> dict[str, Any]:
        resolved: dict[str, Any] = {}
        for key, value in params.items():
            match = PLACEHOLDER.match(value) if isinstance(value, str) else None
            if match is None:
                resolved[key] = value
                continue
            index, field = int(match.group(1)), match.group(2)
            if dry:
                resolved[key] = f"<step {index}.{field}>"
            elif field not in steps[index].output:
                raise PlanError(f"step {index} produced no '{field}'")
            else:
                resolved[key] = steps[index].output[field]
        return resolved

    def _execute(self, run: ActionRun) -> ActionRun:
        rec = run.recommendation
        run.status = RunStatus.EXECUTING
        run.steps = [
            StepRecord(index=i, action_id=s.action_id, params=dict(s.params)) for i, s in enumerate(rec.steps)
        ]
        self._save(run)

        # Dry run every step first. If any step would fail, nothing has changed yet.
        for st in run.steps:
            contract = self._catalog.require(st.action_id)
            req = ExecRequest(
                run_id=run.run_id,
                step_id=str(st.index),
                action_id=st.action_id,
                params=self._resolve(st.params, run.steps, dry=True),
                idempotency_key=f"{run.run_id}:{st.index}:dry",
                dry_run=True,
            )
            result, dry_attempts = self._hub.dry_run(contract.domain, req)
            self._audit.record(
                run.run_id, "dry_run", step=st.index, action=st.action_id, ok=result.ok,
                attempts=dry_attempts, detail=result.detail,
            )
            if not result.ok:
                st.attempts = dry_attempts
                st.status = "failed"
                st.detail = f"dry run failed: {result.detail}"
                run.needs_escalation = True
                return self._finish(
                    run, RunStatus.FAILED, f"dry run failed for step {st.index} ({st.action_id}); nothing was executed"
                )
            st.status = "dry_run_ok"

        completed: list[StepRecord] = []
        for st in run.steps:
            if self.kill_switch_engaged():
                run.needs_escalation = True
                return self._finish(
                    run,
                    RunStatus.KILLED,
                    f"kill switch engaged; {len(completed)} step(s) already executed are left in place for review",
                )
            contract = self._catalog.require(st.action_id)
            try:
                params = self._resolve(st.params, run.steps, dry=False)
            except PlanError as exc:
                st.status = "failed"
                st.detail = str(exc)
                return self._rollback_and_finish(run, completed, f"step {st.index} could not start: {exc}")
            st.params = params

            run.status = RunStatus.EXECUTING
            req = ExecRequest(
                run_id=run.run_id,
                step_id=str(st.index),
                action_id=st.action_id,
                params=params,
                idempotency_key=f"{run.run_id}:{st.index}",
            )
            result, attempts = self._hub.execute(contract.domain, req)
            st.attempts = attempts
            st.detail = result.detail
            st.output = result.output
            st.rollback_token = result.rollback_token
            self._audit.record(
                run.run_id, "step_executed", step=st.index, action=st.action_id, ok=result.ok,
                attempts=attempts, detail=result.detail, replayed=result.replayed,
            )
            if not result.ok:
                st.status = "failed"
                # A failed step may be partly applied; roll it back too if it left a rollback token.
                to_roll = completed + ([st] if st.rollback_token else [])
                return self._rollback_and_finish(
                    run, to_roll, f"step {st.index} ({st.action_id}) failed: {result.detail}"
                )
            st.status = "executed"
            self._save(run)

            run.status = RunStatus.VERIFYING
            verdict = self._verifier.verify(contract.verify, rec.target, params, result)
            self._audit.record(
                run.run_id, "verified", step=st.index, action=st.action_id, ok=verdict.ok, detail=verdict.detail
            )
            if not verdict.ok:
                st.status = "failed"
                st.detail = f"{st.detail}; verification failed: {verdict.detail}"
                return self._rollback_and_finish(
                    run, completed + [st], f"step {st.index} ({st.action_id}) failed verification: {verdict.detail}"
                )
            st.status = "verified"
            completed.append(st)
            self._save(run)

        return self._finish(run, RunStatus.SUCCEEDED, "all steps executed and verified")

    def _rollback_and_finish(self, run: ActionRun, to_roll: list[StepRecord], reason: str) -> ActionRun:
        run.needs_escalation = True
        if not to_roll:
            self._escalate(run, reason)
            return self._finish(run, RunStatus.FAILED, f"{reason}. Nothing had changed, so nothing was rolled back.")

        run.status = RunStatus.ROLLING_BACK
        self._save(run)
        self._audit.record(run.run_id, "rollback_started", reason=reason, steps=[s.index for s in to_roll])

        failed = False
        irreversible: list[str] = []
        for st in reversed(to_roll):
            contract = self._catalog.require(st.action_id)
            if contract.rollback.kind is RollbackKind.NONE:
                st.status = "rollback_skipped"
                st.detail = f"{st.detail}; not reversible: {contract.rollback.description}"
                irreversible.append(st.action_id)
                self._audit.record(run.run_id, "rollback_skipped", step=st.index, action=st.action_id)
                continue
            req = RollbackRequest(
                run_id=run.run_id,
                step_id=str(st.index),
                action_id=st.action_id,
                params=st.params,
                rollback_token=st.rollback_token,
                idempotency_key=f"{run.run_id}:{st.index}",
            )
            result, _ = self._hub.rollback(contract.domain, req)
            self._audit.record(
                run.run_id, "rolled_back", step=st.index, action=st.action_id, ok=result.ok, detail=result.detail
            )
            if result.ok:
                st.status = "rolled_back"
                st.detail = f"{st.detail}; rolled back: {result.detail}"
            else:
                st.status = "rollback_failed"
                st.detail = f"{st.detail}; rollback failed: {result.detail}"
                failed = True

        self._escalate(run, reason)
        note = f" Not reversible and left as is: {', '.join(irreversible)}." if irreversible else ""
        if failed:
            return self._finish(run, RunStatus.ROLLBACK_FAILED, f"{reason}. Rollback failed for at least one step.{note}")
        return self._finish(run, RunStatus.ROLLED_BACK, f"{reason}. Rolled back.{note}")

    def _escalate(self, run: ActionRun, reason: str) -> None:
        # Records the escalation request. A deployment wires `escalate` to the Incident pack's
        # page_oncall so the on-call engineer is paged.
        self._audit.record(run.run_id, "escalation_requested", reason=reason)
        if self._escalate_hook is not None:
            try:
                self._escalate_hook(run, reason)
            except Exception as exc:
                self._audit.record(run.run_id, "escalation_failed", error=f"{type(exc).__name__}: {exc}")

    def _save(self, run: ActionRun) -> None:
        run.updated_at = self._clock()
        self._store.save_run(run)

    def _finish(self, run: ActionRun, status: RunStatus, message: str) -> ActionRun:
        run.status = status
        run.message = message
        self._save(run)
        self._audit.record(run.run_id, "status", status=status.value, message=message)
        return run
