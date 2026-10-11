"""FinOps executor: idle resources, schedules, volumes and sizing.

The connector is a SIMULATED in-memory stand-in for cloud cost and resource APIs. There is
deliberately no handler for ``purchase_commitment``: it is a T3 action that people execute.
"""
from __future__ import annotations

from typing import Any

from action_agent.sdk import ActionHandler, BaseExecutor, ExecResult, create_executor_app


class SimulatedCloud:
    def __init__(self) -> None:
        self.resources: dict[str, dict[str, Any]] = {
            "vm-dev-01": {"state": "running", "size": "D4", "schedule": None},
            "vm-dev-02": {"state": "running", "size": "D8", "schedule": "always-on"},
            "vm-prod-01": {"state": "running", "size": "D16", "schedule": None},
        }
        self.volumes: dict[str, dict[str, Any]] = {
            "vol-0a1": {"attached": False, "size_gb": 200, "deleted": False},
            "vol-0b2": {"attached": True, "size_gb": 500, "deleted": False},
        }
        self.snapshots: dict[str, dict[str, Any]] = {}

    def resource(self, resource_id: str) -> dict[str, Any]:
        return self.resources[resource_id]

    def volume(self, volume_id: str) -> dict[str, Any]:
        return self.volumes[volume_id]


class StopIdleResource(ActionHandler):
    action_id = "stop_idle_resource"

    def __init__(self, cloud: SimulatedCloud) -> None:
        self.cloud = cloud

    def dry_run(self, params: dict[str, Any]) -> ExecResult:
        self.cloud.resource(params["resource_id"])
        return ExecResult(ok=True, detail="dry-run: no change made")

    def execute(self, params: dict[str, Any]) -> ExecResult:
        resource = self.cloud.resource(params["resource_id"])
        previous = resource["state"]
        resource["state"] = "stopped"
        return ExecResult(
            ok=True,
            detail=f"{params['resource_id']} stopped",
            rollback_token={"resource_id": params["resource_id"], "previous_state": previous},
        )

    def rollback(self, params: dict[str, Any], token: dict[str, Any] | None) -> ExecResult:
        assert token is not None
        self.cloud.resource(token["resource_id"])["state"] = token["previous_state"]
        return ExecResult(ok=True, detail=f"{token['resource_id']} restored to {token['previous_state']}")


class ApplySchedule(ActionHandler):
    action_id = "apply_schedule"

    def __init__(self, cloud: SimulatedCloud) -> None:
        self.cloud = cloud

    def dry_run(self, params: dict[str, Any]) -> ExecResult:
        self.cloud.resource(params["resource_id"])
        return ExecResult(ok=True, detail="dry-run: no change made")

    def execute(self, params: dict[str, Any]) -> ExecResult:
        resource = self.cloud.resource(params["resource_id"])
        previous = resource["schedule"]
        resource["schedule"] = params["schedule"]
        return ExecResult(
            ok=True,
            detail=f"schedule '{params['schedule']}' applied to {params['resource_id']}",
            rollback_token={"resource_id": params["resource_id"], "previous_schedule": previous},
        )

    def rollback(self, params: dict[str, Any], token: dict[str, Any] | None) -> ExecResult:
        assert token is not None
        self.cloud.resource(token["resource_id"])["schedule"] = token["previous_schedule"]
        return ExecResult(ok=True, detail=f"schedule restored on {token['resource_id']}")


class DeleteUnattachedVolume(ActionHandler):
    action_id = "delete_unattached_volume"

    def __init__(self, cloud: SimulatedCloud) -> None:
        self.cloud = cloud

    def dry_run(self, params: dict[str, Any]) -> ExecResult:
        volume = self.cloud.volume(params["volume_id"])
        if volume["attached"]:
            return ExecResult(ok=False, detail=f"{params['volume_id']} is attached and will not be deleted")
        return ExecResult(ok=True, detail="dry-run: no change made")

    def execute(self, params: dict[str, Any]) -> ExecResult:
        volume = self.cloud.volume(params["volume_id"])
        if volume["attached"]:
            return ExecResult(ok=False, detail=f"{params['volume_id']} is attached and will not be deleted")
        snapshot_id = f"snap-{params['volume_id']}"
        self.cloud.snapshots[snapshot_id] = {"volume_id": params["volume_id"], "size_gb": volume["size_gb"]}
        volume["deleted"] = True
        return ExecResult(
            ok=True,
            detail=f"{params['volume_id']} deleted after snapshot {snapshot_id}",
            output={"snapshot_id": snapshot_id},
            rollback_token={"volume_id": params["volume_id"], "snapshot_id": snapshot_id},
        )

    def rollback(self, params: dict[str, Any], token: dict[str, Any] | None) -> ExecResult:
        assert token is not None
        self.cloud.snapshots[token["snapshot_id"]]  # the snapshot must still exist
        self.cloud.volume(token["volume_id"])["deleted"] = False
        return ExecResult(ok=True, detail=f"{token['volume_id']} restored from {token['snapshot_id']}")


class RightsizeInstance(ActionHandler):
    action_id = "rightsize_instance"

    def __init__(self, cloud: SimulatedCloud) -> None:
        self.cloud = cloud

    def dry_run(self, params: dict[str, Any]) -> ExecResult:
        self.cloud.resource(params["resource_id"])
        return ExecResult(ok=True, detail="dry-run: no change made")

    def execute(self, params: dict[str, Any]) -> ExecResult:
        resource = self.cloud.resource(params["resource_id"])
        previous = resource["size"]
        resource["size"] = params["new_size"]
        return ExecResult(
            ok=True,
            detail=f"{params['resource_id']} resized from {previous} to {params['new_size']}",
            rollback_token={"resource_id": params["resource_id"], "previous_size": previous},
        )

    def rollback(self, params: dict[str, Any], token: dict[str, Any] | None) -> ExecResult:
        assert token is not None
        self.cloud.resource(token["resource_id"])["size"] = token["previous_size"]
        return ExecResult(ok=True, detail=f"{token['resource_id']} restored to {token['previous_size']}")


class FinOpsExecutor(BaseExecutor):
    def __init__(self) -> None:
        self.cloud = SimulatedCloud()
        super().__init__(
            "finops",
            [
                StopIdleResource(self.cloud),
                ApplySchedule(self.cloud),
                DeleteUnattachedVolume(self.cloud),
                RightsizeInstance(self.cloud),
            ],
        )


app = create_executor_app(FinOpsExecutor())
