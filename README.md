# Action Agent

The execution layer of ARIES. It takes a recommendation, checks it, gets it approved when needed,
runs it on the target system, verifies it worked, and rolls back if it did not. Every step is
recorded in a tamper-evident audit trail.

The core is **deterministic: there is no LLM and no agent framework in v1.** Risk tiers, policy
checks, approvals, execution, verification and rollback are rules, which keeps behaviour
predictable and auditable. An LLM planner can be added later behind the `Planner` interface without
touching the core (see "Planner" below).

## What is built

| Part | What it does |
|---|---|
| **Core service** (`action_agent.core`) | Catalog, plan validation, risk tiers, policy client, trust ladder, approvals, orchestrator, verifier, audit chain, kill switch, HTTP API |
| **Incident executor** | create/update/close ticket, page on-call, run diagnostic runbook, declare major incident |
| **InfraOps executor** | restart service, clear temp files, extend disk, scale node group, reboot host |
| **FinOps executor** | stop idle resource, apply schedule, delete unattached volume, rightsize instance |
| **Executor SDK** (`action_agent.sdk`) | Handler interface, idempotency, and the HTTP app every executor exposes |

16 actions in the catalog. Each declares inputs, preconditions, blast radius, tier, a verification
check and a rollback. `purchase_commitment` is T3, so it has no handler: the agent prepares the
plan and a person executes it.

## How a recommendation flows

1. **Validate:** every action is in the catalog, required inputs are present, step references only point backwards.
2. **Kill switch:** if engaged, nothing runs.
3. **Risk tier:** highest tier of any step. Production can raise a tier (floor), and a large blast radius raises it one level.
4. **Policy check:** asks the Policy Agent. No answer means denied (fail closed).
5. **Trust ladder:** per action, `shadow` (record only), `suggest` (a person acts), `approve_and_run`, or `auto_t1` (T0 and T1 run alone, T2 needs approval). T3 is always a person. A plan runs in the most restrictive mode of its actions.
6. **Approval:** for T2, with an expiry. Policy is checked again when the approval arrives.
7. **Dry run** of every step first. If any step would fail, nothing has changed.
8. **Execute** step by step. Retries reuse one idempotency key, so a retry cannot apply a change twice.
9. **Verify** each step. A failed or unreachable health check counts as failed.
10. **Roll back** completed steps in reverse order on any failure, and flag the run for escalation. Actions that cannot be undone are named in the result, not hidden.

## Run it

```bash
pip install -e ".[dev]"
python -m pytest                       # 41 tests

# Core alone: simulated executors run in-process, policy and health are stubbed.
uvicorn action_agent.core.app:create_app --factory --port 8000
```

Separate services (as in production), without Docker:

```bash
uvicorn action_agent.executors.incident.app:app --port 8001 &
uvicorn action_agent.executors.infra.app:app    --port 8002 &
uvicorn action_agent.executors.finops.app:app   --port 8003 &
AA_EXECUTOR_INCIDENT_URL=http://127.0.0.1:8001 \
AA_EXECUTOR_INFRA_URL=http://127.0.0.1:8002 \
AA_EXECUTOR_FINOPS_URL=http://127.0.0.1:8003 \
AA_DEFAULT_MODE=auto_t1 \
uvicorn action_agent.core.app:create_app --factory --port 8000
```

`docker compose up --build` starts the same four containers.

### Console (prototype UI, VertexMind theme)

With the core running, open http://localhost:8000. It shows what is waiting for approval (with Approve and
Deny), each run as a step lane (dry run, run, verify, roll back), the audit trail, the kill switch, and a
button that checks the audit chain. Catalog and audit-trail screens are included. The colors, fonts and logo mark are a placeholder theme in the first CSS block, not official brand assets. Four sample scenarios start runs without any `curl`. It is one HTML file
(`core/static/index.html`) that calls the same API. There is no sign-in: the approver name is typed in and
not verified, and the page says so.

A separate React version of the console lives in `ui/` (see `ui/README.md`). It talks to the same API.

### Try it

```bash
curl -s localhost:8000/v1/recommendations -H 'content-type: application/json' -d '{
  "recommendation_id": "rec-1", "target": "payments", "environment": "prod", "confidence": 0.93,
  "steps": [
    {"action_id": "create_ticket", "params": {"title": "Payments failing", "severity": "high", "service": "payments"}},
    {"action_id": "scale_node_group", "params": {"group": "payments-ng", "desired": 5}},
    {"action_id": "update_ticket", "params": {"ticket_id": "$step[0].ticket_id", "note": "scaled to 5"}}
  ]}'
curl -s -X POST localhost:8000/v1/runs/<run_id>/approve -H 'content-type: application/json' -d '{"approver": "you"}'
curl -s localhost:8000/v1/runs/<run_id>/audit
curl -s localhost:8000/v1/audit/verify
```

API: `POST /v1/recommendations`, `GET /v1/runs`, `GET /v1/runs/{id}`, `POST /v1/runs/{id}/approve|deny`,
`GET /v1/runs/{id}/audit`, `GET /v1/audit/verify`, `GET|POST /v1/killswitch`, `GET /v1/catalog`.
A repeated `recommendation_id` returns the same run (HTTP 200) and never runs twice.

### Configuration

| Variable | Meaning |
|---|---|
| `AA_DB_PATH` | SQLite file (default `data/action_agent.db`) |
| `AA_DEFAULT_MODE` | `shadow`, `suggest`, `approve_and_run` (default), `auto_t1` |
| `AA_MODES` | Per-action override, e.g. `restart_service=auto_t1,create_ticket=auto_t1` |
| `AA_APPROVAL_TTL_MIN` | Minutes an approval stays open (default 30) |
| `AA_POLICY_URL` | Policy Agent base URL. Unset uses the local stub. |
| `AA_HEALTH_URL` | ARIES monitoring base URL. Unset uses the local stub. |
| `AA_EXECUTOR_INCIDENT_URL`, `_INFRA_URL`, `_FINOPS_URL` | Executor URLs. Unset runs that executor in-process. |

## What is simulated, stubbed or assumed

Be clear about this before showing it to anyone as more than a working skeleton.

- **Target systems are simulated.** The executors act on in-memory stand-ins (`SimulatedITSM`, `SimulatedInfra`, `SimulatedCloud`). No real EasyVista, paging tool, cloud, Terraform or Ansible is called. Replace each `Simulated*` class with a real connector that has the same methods.
- **Policy Agent and ARIES monitoring are stubbed.** `HttpPolicyClient` (`POST /v1/evaluate`) and `HttpHealthSource` (`POST /v1/health-check`) use request and response shapes I assumed. Align them with the real APIs.
- **No authentication.** The approver name is self-asserted. Put the API behind SSO or a gateway and take the approver from the verified identity before real use.
- **Synchronous and single-process.** A plan runs inside the request under one lock, with SQLite storage. Fine for a pilot. For scale, move execution onto a queue with a durable workflow engine and a server database, keeping the same state machine.
- **Escalation is recorded, not delivered.** A failed run sets `needs_escalation` and writes an audit event. Wire the `escalate` hook to the Incident pack's `page_oncall` to actually page someone.
- **Audit chain detects tampering, it does not prevent it.** Ship entries to write-once storage as well.
- **Kill switch stops forward execution.** Steps already executed stay in place and are flagged for review. It does not trigger rollbacks.
- **Multi-subscription and multi-cloud access is not built.** Executors take a base URL. Per-account identities, delegated access and private-network runners are the next layer, as designed in the deck.
- **SecOps, DREOps, AppOps and DevOps packs are not built**, so the rollback step in the deck's 2 a.m. example (an AppOps action) is not available yet.
- **Docker files are untested.** I could not run Docker here. The same services were run as separate processes over HTTP, and all 41 tests pass.

## Planner

`Planner.plan(recommendation) -> recommendation` is the plug point. v1 passes ARIES's structured
steps through. A planner that uses an LLM (for example one built on Microsoft Agent Framework) to
turn free text into catalog steps implements the same interface. Its output still goes through plan
validation, the policy check and the risk tier, so a model can propose steps but cannot bypass the
controls.

## Adding an action or a domain

1. Add an `ActionContract` to `core/catalog.py`: inputs, tier, verification check, rollback.
2. Add an `ActionHandler` to the domain's executor with `execute` (and `rollback` unless the contract says `none`). Return a `rollback_token` from `execute` with whatever the rollback needs.
3. A test checks that every non-T3 catalog action has a handler. For a new domain, add an executor app, register its URL in `core/config.py` and `core/wiring.py`, and add a Compose service.
