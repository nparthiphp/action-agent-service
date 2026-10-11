"""InfraOps executor: services, disks, node groups and hosts.

The connector is a SIMULATED in-memory stand-in. A real build would replace ``SimulatedInfra``
with cloud API, Terraform and Ansible connectors exposing the same methods.
"""
from __future__ import annotations

from typing import Any

from action_agent.sdk import ActionHandler, BaseExecutor, ExecResult, create_executor_app


class SimulatedInfra:
    def __init__(self) -> None:
        self.hosts: dict[str, dict[str, Any]] = {
            "web-01": {
                "services": {
                    "payments": {"state": "running", "restarts": 0},
                    "nginx": {"state": "running", "restarts": 0},
                },
                "volumes": {"/data": 100},
                "temp_files": ["a.tmp", "b.tmp", "c.log"],
                "quarantine": [],
                "reboots": 0,
            },
            "web-02": {
                "services": {"payments": {"state": "running", "restarts": 0}},
                "volumes": {"/data": 100},
                "temp_files": [],
                "quarantine": [],
                "reboots": 0,
            },
        }
        self.node_groups: dict[str, dict[str, int]] = {"payments-ng": {"desired": 3, "max": 20}}
        self.review_tasks: list[str] = []

    def host(self, name: str) -> dict[str, Any]:
        return self.hosts[name]

    def node_group(self, name: str) -> dict[str, int]:
        return self.node_groups[name]


class RestartService(ActionHandler):
    action_id = "restart_service"

    def __init__(self, infra: SimulatedInfra) -> None:
        self.infra = infra

    def dry_run(self, params: dict[str, Any]) -> ExecResult:
        self.infra.host(params["host"])["services"][params["service"]]
        return ExecResult(ok=True, detail="dry-run: no change made")

    def execute(self, params: dict[str, Any]) -> ExecResult:
        service = self.infra.host(params["host"])["services"][params["service"]]
        service["restarts"] += 1
        service["state"] = "running"
        return ExecResult(ok=True, detail=f"{params['service']} restarted on {params['host']}")


class ClearTempFiles(ActionHandler):
    action_id = "clear_temp_files"

    def __init__(self, infra: SimulatedInfra) -> None:
        self.infra = infra

    def dry_run(self, params: dict[str, Any]) -> ExecResult:
        self.infra.host(params["host"])
        return ExecResult(ok=True, detail="dry-run: no change made")

    def execute(self, params: dict[str, Any]) -> ExecResult:
        host = self.infra.host(params["host"])
        moved = list(host["temp_files"])
        host["quarantine"].extend(moved)
        host["temp_files"] = []
        return ExecResult(
            ok=True,
            detail=f"{len(moved)} files moved to quarantine on {params['host']}",
            output={"files_moved": len(moved)},
            rollback_token={"host": params["host"], "files": moved},
        )

    def rollback(self, params: dict[str, Any], token: dict[str, Any] | None) -> ExecResult:
        assert token is not None
        host = self.infra.host(token["host"])
        for name in token["files"]:
            host["quarantine"].remove(name)
            host["temp_files"].append(name)
        return ExecResult(ok=True, detail=f"{len(token['files'])} files restored")


class ExtendDisk(ActionHandler):
    action_id = "extend_disk"

    def __init__(self, infra: SimulatedInfra) -> None:
        self.infra = infra

    def dry_run(self, params: dict[str, Any]) -> ExecResult:
        current = self.infra.host(params["host"])["volumes"][params["volume"]]
        if params["new_size_gb"] <= current:
            return ExecResult(ok=False, detail=f"new size must be larger than the current {current} GB")
        return ExecResult(ok=True, detail="dry-run: no change made")

    def execute(self, params: dict[str, Any]) -> ExecResult:
        volumes = self.infra.host(params["host"])["volumes"]
        previous = volumes[params["volume"]]
        if params["new_size_gb"] <= previous:
            return ExecResult(ok=False, detail=f"new size must be larger than the current {previous} GB")
        volumes[params["volume"]] = params["new_size_gb"]
        return ExecResult(
            ok=True,
            detail=f"{params['volume']} on {params['host']} grown from {previous} to {params['new_size_gb']} GB",
            rollback_token={"host": params["host"], "volume": params["volume"], "previous_gb": previous},
        )

    def rollback(self, params: dict[str, Any], token: dict[str, Any] | None) -> ExecResult:
        # Compensating action: a volume cannot be shrunk, so leave it and open a review task.
        assert token is not None
        self.infra.review_tasks.append(
            f"review {token['volume']} on {token['host']}: grown from {token['previous_gb']} GB, not shrinkable"
        )
        return ExecResult(ok=True, detail="volume left at the new size; review task opened")


class ScaleNodeGroup(ActionHandler):
    action_id = "scale_node_group"

    def __init__(self, infra: SimulatedInfra) -> None:
        self.infra = infra

    def dry_run(self, params: dict[str, Any]) -> ExecResult:
        group = self.infra.node_group(params["group"])
        if not 1 <= params["desired"] <= group["max"]:
            return ExecResult(ok=False, detail=f"desired must be between 1 and {group['max']}")
        return ExecResult(ok=True, detail="dry-run: no change made")

    def execute(self, params: dict[str, Any]) -> ExecResult:
        group = self.infra.node_group(params["group"])
        if not 1 <= params["desired"] <= group["max"]:
            return ExecResult(ok=False, detail=f"desired must be between 1 and {group['max']}")
        previous = group["desired"]
        group["desired"] = params["desired"]
        return ExecResult(
            ok=True,
            detail=f"{params['group']} scaled from {previous} to {params['desired']} nodes",
            rollback_token={"group": params["group"], "previous_desired": previous},
        )

    def rollback(self, params: dict[str, Any], token: dict[str, Any] | None) -> ExecResult:
        assert token is not None
        self.infra.node_group(token["group"])["desired"] = token["previous_desired"]
        return ExecResult(ok=True, detail=f"{token['group']} restored to {token['previous_desired']} nodes")


class RebootHost(ActionHandler):
    action_id = "reboot_host"

    def __init__(self, infra: SimulatedInfra) -> None:
        self.infra = infra

    def dry_run(self, params: dict[str, Any]) -> ExecResult:
        self.infra.host(params["host"])
        return ExecResult(ok=True, detail="dry-run: no change made")

    def execute(self, params: dict[str, Any]) -> ExecResult:
        host = self.infra.host(params["host"])
        host["reboots"] += 1
        return ExecResult(
            ok=True,
            detail=f"{params['host']} rebooted",
            rollback_token={"host": params["host"]},
        )

    def rollback(self, params: dict[str, Any], token: dict[str, Any] | None) -> ExecResult:
        # Compensating action: a reboot cannot be undone, so make sure every service is running.
        assert token is not None
        for service in self.infra.host(token["host"])["services"].values():
            service["state"] = "running"
        return ExecResult(ok=True, detail="all services confirmed running after the reboot")


class InfraExecutor(BaseExecutor):
    def __init__(self) -> None:
        self.infra = SimulatedInfra()
        super().__init__(
            "infra",
            [
                RestartService(self.infra),
                ClearTempFiles(self.infra),
                ExtendDisk(self.infra),
                ScaleNodeGroup(self.infra),
                RebootHost(self.infra),
            ],
        )


app = create_executor_app(InfraExecutor())
