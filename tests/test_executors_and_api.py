from fastapi.testclient import TestClient

from action_agent.core.app import create_app
from action_agent.core.autonomy import Mode
from action_agent.core.hub import HttpExecutorClient
from action_agent.executors.incident.app import IncidentExecutor
from action_agent.sdk import ExecRequest, RollbackRequest, create_executor_app

from helpers import make_env


def _request(key: str = "run-1:0", **params) -> ExecRequest:
    base = {"title": "t", "severity": "high", "service": "payments"}
    return ExecRequest(
        run_id="run-1", step_id="0", action_id="create_ticket", params=params or base, idempotency_key=key
    )


def test_executor_replays_the_stored_result_for_a_repeated_key():
    executor = IncidentExecutor()
    first = executor.execute(_request())
    second = executor.execute(_request())
    assert first.ok and not first.replayed
    assert second.replayed and second.output == first.output
    assert len(executor.itsm.tickets) == 1


def test_executor_turns_connector_errors_into_failed_results():
    executor = IncidentExecutor()
    req = ExecRequest(
        run_id="r", step_id="0", action_id="close_ticket",
        params={"ticket_id": "INC-nope", "resolution": "x"}, idempotency_key="k",
    )
    result = executor.execute(req)
    assert not result.ok and "unknown or missing value" in result.detail


def test_executor_rollback_is_idempotent():
    executor = IncidentExecutor()
    created = executor.execute(_request())
    rollback = RollbackRequest(
        run_id="run-1", step_id="0", action_id="create_ticket", params={},
        rollback_token=created.rollback_token, idempotency_key="run-1:0",
    )
    assert executor.rollback(rollback).ok
    assert executor.rollback(rollback).replayed
    assert executor.itsm.tickets["INC1001"]["status"] == "cancelled"


def test_http_executor_client_talks_to_the_executor_app():
    executor = IncidentExecutor()
    http = TestClient(create_executor_app(executor))
    client = HttpExecutorClient("http://testserver", client=http)
    assert http.get("/actions").json()["actions"] == executor.action_ids

    result = client.execute(_request())
    assert result.ok and result.output["ticket_id"] == "INC1001"
    assert client.execute(_request()).replayed
    unknown = http.post("/execute", json=_request().model_copy(update={"action_id": "nope"}).model_dump())
    assert unknown.status_code == 404


def test_core_api_end_to_end_with_approval_and_audit():
    env = make_env(default_mode=Mode.APPROVE_AND_RUN)
    api = TestClient(create_app(env.orch))

    body = {
        "recommendation_id": "rec-api-1",
        "target": "payments",
        "environment": "prod",
        "confidence": 0.92,
        "rationale": "disk 96 percent full",
        "steps": [
            {"action_id": "extend_disk", "params": {"host": "web-01", "volume": "/data", "new_size_gb": 200}}
        ],
    }
    created = api.post("/v1/recommendations", json=body)
    assert created.status_code == 201
    run = created.json()
    assert run["status"] == "awaiting_approval" and run["tier"] == "T2"

    assert api.post("/v1/recommendations", json=body).status_code == 200  # duplicate, same run

    approved = api.post(f"/v1/runs/{run['run_id']}/approve", json={"approver": "priya", "comment": "ok"})
    assert approved.status_code == 200 and approved.json()["status"] == "succeeded"
    assert api.post(f"/v1/runs/{run['run_id']}/approve", json={"approver": "priya"}).status_code == 409

    events = [e["event"] for e in api.get(f"/v1/runs/{run['run_id']}/audit").json()]
    assert "approved" in events and "step_executed" in events
    assert api.get("/v1/audit/verify").json() == {"ok": True, "broken_at": None}


def test_core_api_errors_and_kill_switch():
    env = make_env()
    api = TestClient(create_app(env.orch))
    assert api.get("/v1/runs/run-missing").status_code == 404
    assert api.post("/v1/recommendations", json={"recommendation_id": "x"}).status_code == 422
    assert len(api.get("/v1/catalog").json()) == 16

    assert api.post("/v1/killswitch", json={"engaged": True, "by": "oncall"}).json() == {"engaged": True}
    body = {
        "recommendation_id": "rec-k", "target": "t", "environment": "nonprod", "confidence": 0.5,
        "steps": [{"action_id": "run_diagnostic_runbook", "params": {"service": "payments", "runbook": "r"}}],
    }
    assert api.post("/v1/recommendations", json=body).json()["status"] == "killed"
    assert api.get("/health").json()["kill_switch"] is True


def test_console_page_is_served():
    from fastapi.testclient import TestClient

    from action_agent.core.app import create_app

    client = TestClient(create_app(make_env().orch))
    res = client.get("/ui")
    assert res.status_code == 200 and "Action Agent" in res.text
    assert client.get("/", follow_redirects=False).status_code in (302, 307)


def test_recent_audit_endpoint_lists_newest_first():
    from fastapi.testclient import TestClient

    from action_agent.core.app import create_app
    from helpers import rec

    env = make_env()
    env.orch.submit(rec([("create_ticket", {"title": "t", "severity": "low", "service": "s"})]))
    client = TestClient(create_app(env.orch))
    rows = client.get("/v1/audit?limit=5").json()
    assert rows and len(rows) <= 5
    assert [r["seq"] for r in rows] == sorted((r["seq"] for r in rows), reverse=True)


def test_cors_is_off_by_default_and_on_when_configured(monkeypatch):
    from fastapi.testclient import TestClient

    from action_agent.core.app import create_app

    hdr = {"Origin": "http://ui.example", "Access-Control-Request-Method": "POST"}
    monkeypatch.delenv("AA_CORS_ORIGINS", raising=False)
    assert "access-control-allow-origin" not in TestClient(create_app(make_env().orch)).options("/v1/runs", headers=hdr).headers
    monkeypatch.setenv("AA_CORS_ORIGINS", "http://ui.example")
    res = TestClient(create_app(make_env().orch)).options("/v1/runs", headers=hdr)
    assert res.headers.get("access-control-allow-origin") == "http://ui.example"
