from datetime import timedelta

from action_agent.core.autonomy import Mode
from action_agent.core.hub import ExecutorUnavailable
from action_agent.core.models import RunStatus, Tier
from action_agent.core.policy import StubPolicyClient
from action_agent.sdk import ExecResult

from helpers import TICKET, make_env, rec

NOTE = ("update_ticket", {"ticket_id": "$step[0].ticket_id", "note": "rolled back the release"})
RESTART = ("restart_service", {"host": "web-01", "service": "payments"})
EXTEND = ("extend_disk", {"host": "web-01", "volume": "/data", "new_size_gb": 200})
SCALE = ("scale_node_group", {"group": "payments-ng", "desired": 5})


# ---- the happy paths ------------------------------------------------------------------------
def test_t1_plan_runs_by_itself_in_auto_mode_and_chains_step_output():
    env = make_env()
    run, created = env.orch.submit(rec([TICKET, NOTE]))
    assert created and run.status is RunStatus.SUCCEEDED
    assert run.tier == Tier.T1
    assert [s.status for s in run.steps] == ["verified", "verified"]
    ticket = env.incident.itsm.tickets["INC1001"]
    assert ticket["notes"] == ["rolled back the release"]


def test_default_mode_waits_for_approval_then_runs():
    env = make_env(default_mode=Mode.APPROVE_AND_RUN)
    run, _ = env.orch.submit(rec([RESTART]))
    assert run.status is RunStatus.AWAITING_APPROVAL
    assert env.infra.infra.host("web-01")["services"]["payments"]["restarts"] == 0

    run = env.orch.approve(run.run_id, "priya")
    assert run.status is RunStatus.SUCCEEDED
    assert env.infra.infra.host("web-01")["services"]["payments"]["restarts"] == 1
    assert run.approval and run.approval.decided_by == "priya"


def test_t2_needs_approval_even_in_auto_t1_mode():
    env = make_env()
    run, _ = env.orch.submit(rec([EXTEND]))
    assert run.status is RunStatus.AWAITING_APPROVAL
    assert env.infra.infra.host("web-01")["volumes"]["/data"] == 100


def test_t3_is_never_executed_and_comes_with_a_prepared_plan():
    env = make_env()
    run, _ = env.orch.submit(
        rec([("purchase_commitment", {"commitment_id": "ri-1", "term_months": 12})])
    )
    assert run.status is RunStatus.HUMAN_REQUIRED
    assert run.steps == []
    assert run.human_plan and run.human_plan[0]["rollback"].startswith("compensate")


def test_shadow_mode_records_the_plan_and_executes_nothing():
    env = make_env(modes={"restart_service": Mode.SHADOW})
    run, _ = env.orch.submit(rec([RESTART]))
    assert run.status is RunStatus.SHADOWED and run.human_plan
    assert env.infra.infra.host("web-01")["services"]["payments"]["restarts"] == 0


def test_suggest_mode_hands_the_plan_to_a_person():
    env = make_env(modes={"restart_service": Mode.SUGGEST})
    run, _ = env.orch.submit(rec([TICKET, RESTART]))
    assert run.status is RunStatus.AWAITING_HUMAN
    assert env.incident.itsm.tickets == {}


# ---- controls ---------------------------------------------------------------------------------
def test_policy_denial_stops_the_run():
    env = make_env(policy=StubPolicyClient(protected_targets={"payments"}))
    run, _ = env.orch.submit(rec([TICKET]))
    assert run.status is RunStatus.REJECTED_BY_POLICY
    assert env.incident.itsm.tickets == {}


def test_policy_failure_fails_closed():
    class Broken:
        def evaluate(self, req):
            raise RuntimeError("policy service is down")

    env = make_env(policy=Broken())
    run, _ = env.orch.submit(rec([TICKET]))
    assert run.status is RunStatus.REJECTED_BY_POLICY
    assert "fail closed" in run.message


def test_policy_is_checked_again_when_the_approval_arrives():
    policy = StubPolicyClient()
    env = make_env(policy=policy, default_mode=Mode.APPROVE_AND_RUN)
    run, _ = env.orch.submit(rec([RESTART]))
    policy.protected_targets.add("payments")  # the situation changed while waiting
    run = env.orch.approve(run.run_id, "priya")
    assert run.status is RunStatus.REJECTED_BY_POLICY
    assert env.infra.infra.host("web-01")["services"]["payments"]["restarts"] == 0


def test_invalid_plans_are_rejected_before_anything_runs():
    env = make_env()
    run, _ = env.orch.submit(rec([("no_such_action", {})]))
    assert run.status is RunStatus.INVALID
    run, _ = env.orch.submit(rec([("create_ticket", {"title": "x"})], rec_id="rec-2"))
    assert run.status is RunStatus.INVALID and "missing input" in run.message


def test_kill_switch_blocks_new_runs_and_pending_approvals():
    env = make_env(default_mode=Mode.APPROVE_AND_RUN)
    waiting, _ = env.orch.submit(rec([RESTART], rec_id="rec-wait"))
    env.orch.set_kill_switch(True, "oncall")

    blocked, _ = env.orch.submit(rec([TICKET], rec_id="rec-new"))
    assert blocked.status is RunStatus.KILLED
    assert env.orch.approve(waiting.run_id, "priya").status is RunStatus.KILLED
    assert env.infra.infra.host("web-01")["services"]["payments"]["restarts"] == 0

    env.orch.set_kill_switch(False, "oncall")
    again, _ = env.orch.submit(rec([TICKET], rec_id="rec-after"))
    assert again.status is RunStatus.AWAITING_APPROVAL


def test_approval_expires():
    env = make_env(ttl_minutes=30)
    run, _ = env.orch.submit(rec([EXTEND]))
    env.clock.advance(minutes=31)
    run = env.orch.approve(run.run_id, "priya")
    assert run.status is RunStatus.EXPIRED
    assert env.infra.infra.host("web-01")["volumes"]["/data"] == 100


def test_denied_runs_do_nothing():
    env = make_env()
    run, _ = env.orch.submit(rec([EXTEND]))
    run = env.orch.deny(run.run_id, "priya", "not now")
    assert run.status is RunStatus.DENIED
    assert env.infra.infra.host("web-01")["volumes"]["/data"] == 100


def test_the_same_recommendation_is_never_run_twice():
    env = make_env()
    first, created_first = env.orch.submit(rec([TICKET]))
    second, created_second = env.orch.submit(rec([TICKET]))
    assert created_first and not created_second
    assert first.run_id == second.run_id
    assert len(env.incident.itsm.tickets) == 1


# ---- failure handling -------------------------------------------------------------------------
def test_dry_run_failure_means_nothing_was_executed():
    env = make_env()
    bad_scale = ("scale_node_group", {"group": "no-such-group", "desired": 5})
    run, _ = env.orch.submit(rec([TICKET, bad_scale]))
    run = env.orch.approve(run.run_id, "priya")
    assert run.status is RunStatus.FAILED and "nothing was executed" in run.message
    assert env.incident.itsm.tickets == {}


def test_verification_failure_rolls_back_in_reverse_and_flags_the_irreversible():
    env = make_env(unhealthy=("payments",))
    run, _ = env.orch.submit(rec([TICKET, RESTART]))  # both T1, so they run without approval
    assert run.status is RunStatus.ROLLED_BACK and run.needs_escalation
    assert [s.status for s in run.steps] == ["rolled_back", "rollback_skipped"]
    assert env.incident.itsm.tickets["INC1001"]["status"] == "cancelled"
    assert "Not reversible" in run.message and "restart_service" in run.message


def test_execute_failure_rolls_back_completed_steps():
    class FailScale:
        def __init__(self, inner):
            self.inner = inner

        def dry_run(self, req):
            return self.inner.dry_run(req)

        def execute(self, req):
            if req.action_id == "scale_node_group":
                return ExecResult(ok=False, detail="cloud API refused the change")
            return self.inner.execute(req)

        def rollback(self, req):
            return self.inner.rollback(req)

    env = make_env(wrap=lambda domain, client: FailScale(client) if domain == "infra" else client)
    run, _ = env.orch.submit(rec([TICKET, SCALE]))
    run = env.orch.approve(run.run_id, "priya")
    assert run.status is RunStatus.ROLLED_BACK
    assert env.incident.itsm.tickets["INC1001"]["status"] == "cancelled"
    assert env.infra.infra.node_group("payments-ng")["desired"] == 3


def test_rollback_failure_is_reported_not_hidden():
    class FailRollback:
        def __init__(self, inner):
            self.inner = inner

        def dry_run(self, req):
            return self.inner.dry_run(req)

        def execute(self, req):
            return self.inner.execute(req)

        def rollback(self, req):
            return ExecResult(ok=False, detail="ticket system unreachable")

    env = make_env(unhealthy=("payments",), wrap=lambda d, c: FailRollback(c) if d == "incident" else c)
    run, _ = env.orch.submit(rec([TICKET, ("restart_service", {"host": "web-01", "service": "payments"})]))
    assert run.status is RunStatus.ROLLBACK_FAILED and run.needs_escalation
    assert run.steps[0].status == "rollback_failed" and "unreachable" in run.steps[0].detail


def test_transient_executor_errors_are_retried_without_applying_twice():
    class Flaky:
        def __init__(self, inner):
            self.inner = inner
            self.calls = 0

        def dry_run(self, req):
            return self.inner.dry_run(req)

        def execute(self, req):
            self.calls += 1
            result = self.inner.execute(req)  # the change lands, but the answer is lost
            if self.calls == 1:
                raise ExecutorUnavailable("connection reset")
            return result

        def rollback(self, req):
            return self.inner.rollback(req)

    flaky_holder = {}

    def wrap(domain, client):
        if domain == "incident":
            flaky_holder["client"] = Flaky(client)
            return flaky_holder["client"]
        return client

    env = make_env(wrap=wrap)
    run, _ = env.orch.submit(rec([TICKET]))
    assert run.status is RunStatus.SUCCEEDED
    assert run.steps[0].attempts == 2
    assert len(env.incident.itsm.tickets) == 1  # the idempotency key stopped a second ticket
    assert run.steps[0].output["ticket_id"] == "INC1001"


# ---- audit ----------------------------------------------------------------------------------------
def test_audit_trail_records_the_run_and_verifies():
    env = make_env()
    run, _ = env.orch.submit(rec([TICKET, NOTE]))
    events = [e["event"] for e in env.audit.entries(run.run_id)]
    assert events[0] == "received" and events[-1] == "status"
    assert {"policy_decision", "risk_and_mode", "dry_run", "step_executed", "verified"} <= set(events)
    assert env.audit.verify() == (True, None)


def test_audit_chain_detects_tampering():
    env = make_env()
    env.orch.submit(rec([TICKET, NOTE]))
    with env.store.lock:
        env.store._conn.execute("UPDATE audit SET data = '{\"edited\": true}' WHERE seq = 2")
        env.store._conn.commit()
    ok, broken_at = env.audit.verify()
    assert not ok and broken_at == 2
