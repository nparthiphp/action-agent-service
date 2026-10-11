"""Incident executor: ticketing, paging and diagnostics.

The connectors here are SIMULATED in-memory stand-ins for an ITSM (such as EasyVista), a paging
tool and a runbook runner. Replace each ``Simulated*`` class with a real connector that has the
same methods. The handlers and the contracts in the catalog stay the same.
"""
from __future__ import annotations

from typing import Any

from action_agent.sdk import ActionHandler, BaseExecutor, ExecResult, create_executor_app


class SimulatedITSM:
    def __init__(self) -> None:
        self.tickets: dict[str, dict[str, Any]] = {}
        self._seq = 1000

    def create(self, title: str, severity: str, service: str) -> str:
        self._seq += 1
        tid = f"INC{self._seq}"
        self.tickets[tid] = {
            "title": title,
            "severity": severity,
            "service": service,
            "status": "open",
            "notes": [],
            "major": False,
            "resolution": None,
        }
        return tid

    def get(self, ticket_id: str) -> dict[str, Any]:
        return self.tickets[ticket_id]  # KeyError for an unknown ticket


class SimulatedPaging:
    def __init__(self) -> None:
        self.pages: list[dict[str, str]] = []

    def page(self, service: str, message: str) -> str:
        self.pages.append({"service": service, "message": message})
        return f"PG{len(self.pages)}"


class SimulatedRunbooks:
    """Canned diagnostic findings. A real runner would execute the runbook and return its output."""

    _FINDINGS = {
        "payments": [
            "deployment finished 14 minutes before the first error",
            "error rate 38 percent on /charge",
            "connection pool 96 percent used",
        ],
    }

    def run(self, service: str, runbook: str) -> list[str]:
        return self._FINDINGS.get(service, ["no anomalies found"])


class CreateTicket(ActionHandler):
    action_id = "create_ticket"

    def __init__(self, itsm: SimulatedITSM) -> None:
        self.itsm = itsm

    def execute(self, params: dict[str, Any]) -> ExecResult:
        tid = self.itsm.create(params["title"], params["severity"], params["service"])
        return ExecResult(
            ok=True,
            detail=f"ticket {tid} created",
            output={"ticket_id": tid},
            rollback_token={"ticket_id": tid},
        )

    def rollback(self, params: dict[str, Any], token: dict[str, Any] | None) -> ExecResult:
        assert token is not None
        self.itsm.get(token["ticket_id"])["status"] = "cancelled"
        return ExecResult(ok=True, detail=f"ticket {token['ticket_id']} cancelled")


class UpdateTicket(ActionHandler):
    action_id = "update_ticket"

    def __init__(self, itsm: SimulatedITSM) -> None:
        self.itsm = itsm

    def dry_run(self, params: dict[str, Any]) -> ExecResult:
        ticket_id = params["ticket_id"]
        # A ticket created by an earlier step does not exist yet during the dry run.
        if not str(ticket_id).startswith("<step"):
            self.itsm.get(ticket_id)
        return ExecResult(ok=True, detail="dry-run: no change made")

    def execute(self, params: dict[str, Any]) -> ExecResult:
        ticket = self.itsm.get(params["ticket_id"])
        ticket["notes"].append(params["note"])
        index = len(ticket["notes"]) - 1
        return ExecResult(
            ok=True,
            detail=f"note added to {params['ticket_id']}",
            rollback_token={"ticket_id": params["ticket_id"], "index": index},
        )

    def rollback(self, params: dict[str, Any], token: dict[str, Any] | None) -> ExecResult:
        assert token is not None
        self.itsm.get(token["ticket_id"])["notes"].pop(token["index"])
        return ExecResult(ok=True, detail=f"note removed from {token['ticket_id']}")


class PageOncall(ActionHandler):
    action_id = "page_oncall"

    def __init__(self, paging: SimulatedPaging) -> None:
        self.paging = paging

    def execute(self, params: dict[str, Any]) -> ExecResult:
        page_id = self.paging.page(params["service"], params["message"])
        return ExecResult(ok=True, detail=f"page {page_id} sent", output={"page_id": page_id})


class RunDiagnosticRunbook(ActionHandler):
    action_id = "run_diagnostic_runbook"

    def __init__(self, runbooks: SimulatedRunbooks) -> None:
        self.runbooks = runbooks

    def execute(self, params: dict[str, Any]) -> ExecResult:
        findings = self.runbooks.run(params["service"], params["runbook"])
        return ExecResult(ok=True, detail="runbook completed", output={"findings": findings})


class CloseTicket(ActionHandler):
    action_id = "close_ticket"

    def __init__(self, itsm: SimulatedITSM) -> None:
        self.itsm = itsm

    def dry_run(self, params: dict[str, Any]) -> ExecResult:
        if not str(params["ticket_id"]).startswith("<step"):
            self.itsm.get(params["ticket_id"])
        return ExecResult(ok=True, detail="dry-run: no change made")

    def execute(self, params: dict[str, Any]) -> ExecResult:
        ticket = self.itsm.get(params["ticket_id"])
        previous = ticket["status"]
        ticket["status"] = "closed"
        ticket["resolution"] = params["resolution"]
        return ExecResult(
            ok=True,
            detail=f"ticket {params['ticket_id']} closed",
            rollback_token={"ticket_id": params["ticket_id"], "previous_status": previous},
        )

    def rollback(self, params: dict[str, Any], token: dict[str, Any] | None) -> ExecResult:
        assert token is not None
        ticket = self.itsm.get(token["ticket_id"])
        ticket["status"] = token["previous_status"]
        ticket["resolution"] = None
        return ExecResult(ok=True, detail=f"ticket {token['ticket_id']} reopened")


class DeclareMajorIncident(ActionHandler):
    action_id = "declare_major_incident"

    def __init__(self, itsm: SimulatedITSM) -> None:
        self.itsm = itsm

    def dry_run(self, params: dict[str, Any]) -> ExecResult:
        if not str(params["ticket_id"]).startswith("<step"):
            self.itsm.get(params["ticket_id"])
        return ExecResult(ok=True, detail="dry-run: no change made")

    def execute(self, params: dict[str, Any]) -> ExecResult:
        self.itsm.get(params["ticket_id"])["major"] = True
        return ExecResult(
            ok=True,
            detail=f"major incident declared on {params['ticket_id']}",
            rollback_token={"ticket_id": params["ticket_id"]},
        )

    def rollback(self, params: dict[str, Any], token: dict[str, Any] | None) -> ExecResult:
        assert token is not None
        self.itsm.get(token["ticket_id"])["major"] = False
        return ExecResult(ok=True, detail="major incident declaration withdrawn")


class IncidentExecutor(BaseExecutor):
    def __init__(self) -> None:
        self.itsm = SimulatedITSM()
        self.paging = SimulatedPaging()
        self.runbooks = SimulatedRunbooks()
        super().__init__(
            "incident",
            [
                CreateTicket(self.itsm),
                UpdateTicket(self.itsm),
                PageOncall(self.paging),
                RunDiagnosticRunbook(self.runbooks),
                CloseTicket(self.itsm),
                DeclareMajorIncident(self.itsm),
            ],
        )


app = create_executor_app(IncidentExecutor())
