"""HTTP API of the Action Agent core.

There is NO authentication in this build and the approver name is self-asserted. Put the API behind
your SSO or API gateway, and take the approver identity from the verified token, before real use.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import os

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

from action_agent import __version__

from .config import Settings
from .models import ActionContract, ActionRun, Recommendation
from .orchestrator import InvalidState, Orchestrator, RunNotFound
from .wiring import build_orchestrator


_CONSOLE = Path(__file__).parent / "static" / "index.html"


class DecisionBody(BaseModel):
    approver: str
    comment: str = ""


class KillSwitchBody(BaseModel):
    engaged: bool
    by: str


def create_app(orchestrator: Orchestrator | None = None) -> FastAPI:
    orch = orchestrator or build_orchestrator(Settings.from_env())
    app = FastAPI(title="Action Agent core", version=__version__)

    # Only needed when the React console is served from a different origin than the core.
    # The dev server and the nginx image proxy /v1 to the core, so they do not need it.
    origins = [o.strip() for o in os.environ.get("AA_CORS_ORIGINS", "").split(",") if o.strip()]
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["content-type"])

    @app.exception_handler(RunNotFound)
    async def _not_found(_request: Any, exc: RunNotFound) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": f"run not found: {exc}"})

    @app.exception_handler(InvalidState)
    async def _invalid_state(_request: Any, exc: InvalidState) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(ValueError)
    async def _bad_value(_request: Any, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/ui")

    @app.get("/ui", include_in_schema=False)
    def console() -> FileResponse:
        return FileResponse(_CONSOLE, media_type="text/html")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__, "kill_switch": orch.kill_switch_engaged()}

    @app.get("/v1/catalog", response_model=list[ActionContract])
    def catalog() -> list[ActionContract]:
        return orch.catalog.all()

    @app.post("/v1/recommendations", response_model=ActionRun)
    def submit(rec: Recommendation, response: Response) -> ActionRun:
        run, created = orch.submit(rec)
        response.status_code = 201 if created else 200
        return run

    @app.get("/v1/runs", response_model=list[ActionRun])
    def runs(limit: int = 50) -> list[ActionRun]:
        return orch.list_runs(limit)

    @app.get("/v1/runs/{run_id}", response_model=ActionRun)
    def run(run_id: str) -> ActionRun:
        return orch.get_run(run_id)

    @app.post("/v1/runs/{run_id}/approve", response_model=ActionRun)
    def approve(run_id: str, body: DecisionBody) -> ActionRun:
        return orch.approve(run_id, body.approver, body.comment)

    @app.post("/v1/runs/{run_id}/deny", response_model=ActionRun)
    def deny(run_id: str, body: DecisionBody) -> ActionRun:
        return orch.deny(run_id, body.approver, body.comment)

    @app.get("/v1/runs/{run_id}/audit")
    def run_audit(run_id: str) -> list[dict[str, Any]]:
        orch.get_run(run_id)
        return orch.audit.entries(run_id)

    @app.get("/v1/audit")
    def audit_recent(limit: int = 200) -> list[dict[str, Any]]:
        """Most recent audit entries across all runs, newest first."""
        return list(reversed(orch.audit.entries()[-max(1, min(limit, 1000)):]))

    @app.get("/v1/audit/verify")
    def audit_verify() -> dict[str, Any]:
        ok, broken_at = orch.audit.verify()
        return {"ok": ok, "broken_at": broken_at}

    @app.get("/v1/killswitch")
    def killswitch_state() -> dict[str, bool]:
        return {"engaged": orch.kill_switch_engaged()}

    @app.post("/v1/killswitch")
    def killswitch_set(body: KillSwitchBody) -> dict[str, bool]:
        orch.set_kill_switch(body.engaged, body.by)
        return {"engaged": orch.kill_switch_engaged()}

    return app
