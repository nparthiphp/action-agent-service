"""The action catalog: every action the agent may run, as a typed and versioned contract."""
from __future__ import annotations

from typing import Iterable

from .models import (
    ActionContract,
    RollbackKind,
    RollbackSpec,
    Tier,
    VerifySpec,
)

R = RollbackKind


class Catalog:
    def __init__(self, contracts: Iterable[ActionContract]) -> None:
        self._contracts: dict[str, ActionContract] = {}
        for contract in contracts:
            if contract.action_id in self._contracts:
                raise ValueError(f"duplicate action in catalog: {contract.action_id}")
            self._contracts[contract.action_id] = contract

    def get(self, action_id: str) -> ActionContract | None:
        return self._contracts.get(action_id)

    def require(self, action_id: str) -> ActionContract:
        contract = self._contracts.get(action_id)
        if contract is None:
            raise KeyError(f"unknown action: {action_id}")
        return contract

    def all(self) -> list[ActionContract]:
        return list(self._contracts.values())

    def by_domain(self, domain: str) -> list[ActionContract]:
        return [c for c in self._contracts.values() if c.domain == domain]

    def domains(self) -> list[str]:
        return sorted({c.domain for c in self._contracts.values()})


def _contract(
    action_id: str,
    domain: str,
    summary: str,
    inputs: list[str],
    tier: Tier,
    blast: str,
    verify: tuple[str, str],
    rollback: tuple[RollbackKind, str],
    *,
    preconditions: list[str] | None = None,
    floor: Tier | None = None,
    blast_param: str | None = None,
    blast_limit: float | None = None,
) -> ActionContract:
    return ActionContract(
        action_id=action_id,
        domain=domain,
        summary=summary,
        inputs=inputs,
        preconditions=preconditions or [],
        blast_radius=blast,
        tier=tier,
        production_floor=floor,
        blast_param=blast_param,
        blast_limit=blast_limit,
        verify=VerifySpec(check=verify[0], description=verify[1]),
        rollback=RollbackSpec(kind=rollback[0], description=rollback[1]),
    )


def default_catalog() -> Catalog:
    return Catalog(
        [
            # ---- Incident Management -------------------------------------------------------
            _contract(
                "create_ticket", "incident", "Open an incident ticket",
                ["title", "severity", "service"], Tier.T1, "One ticket",
                ("executor_confirmed", "The ticket exists"),
                (R.REVERT, "Cancel the created ticket"),
            ),
            _contract(
                "update_ticket", "incident", "Add a note to a ticket",
                ["ticket_id", "note"], Tier.T1, "One ticket",
                ("executor_confirmed", "The note is on the ticket"),
                (R.REVERT, "Remove the added note"),
            ),
            _contract(
                "page_oncall", "incident", "Page the on-call engineer",
                ["service", "message"], Tier.T1, "One page to one rotation",
                ("executor_confirmed", "The page was accepted by the paging tool"),
                (R.NONE, "A notification cannot be recalled"),
            ),
            _contract(
                "run_diagnostic_runbook", "incident", "Run a read-only diagnostic runbook",
                ["service", "runbook"], Tier.T0, "Read only",
                ("executor_confirmed", "The runbook completed"),
                (R.NONE, "Read only, nothing changes"),
            ),
            _contract(
                "close_ticket", "incident", "Close a ticket with its resolution",
                ["ticket_id", "resolution"], Tier.T1, "One ticket",
                ("executor_confirmed", "The ticket is closed"),
                (R.REVERT, "Reopen the ticket"),
            ),
            _contract(
                "declare_major_incident", "incident", "Declare a major incident",
                ["ticket_id"], Tier.T2, "Triggers the major incident process",
                ("executor_confirmed", "The ticket is flagged as major"),
                (R.REVERT, "Withdraw the declaration"),
            ),
            # ---- InfraOps ------------------------------------------------------------------
            _contract(
                "restart_service", "infra", "Restart a service on a host",
                ["host", "service"], Tier.T1, "One service on one host",
                ("service_healthy", "The service reports healthy after the restart"),
                (R.NONE, "A restart cannot be undone; a failed check escalates to on-call"),
                preconditions=["No change is running on the host"],
            ),
            _contract(
                "clear_temp_files", "infra", "Move temp files to quarantine",
                ["host", "path"], Tier.T1, "Temp files on one host",
                ("host_healthy", "The host reports healthy"),
                (R.REVERT, "Restore the files from quarantine"),
            ),
            _contract(
                "extend_disk", "infra", "Grow a volume",
                ["host", "volume", "new_size_gb"], Tier.T2, "One volume on one host",
                ("host_healthy", "The host reports healthy with the larger volume"),
                (R.COMPENSATE, "A volume cannot be shrunk; leave it and open a review task"),
                preconditions=["The new size is larger than the current size"],
            ),
            _contract(
                "scale_node_group", "infra", "Change the node count of a group",
                ["group", "desired"], Tier.T2, "One node group",
                ("service_healthy", "The workload is healthy at the new size"),
                (R.REVERT, "Restore the previous desired count"),
                blast_param="desired", blast_limit=10,
            ),
            _contract(
                "reboot_host", "infra", "Reboot a host",
                ["host"], Tier.T2, "All services on one host",
                ("host_healthy", "The host and its services are back"),
                (R.COMPENSATE, "A reboot cannot be undone; confirm services are running"),
            ),
            # ---- FinOps --------------------------------------------------------------------
            _contract(
                "stop_idle_resource", "finops", "Stop an idle resource",
                ["resource_id"], Tier.T1, "One resource",
                ("resource_state", "The resource is stopped and nothing depends on it"),
                (R.REVERT, "Start the resource again"),
                floor=Tier.T2,
            ),
            _contract(
                "apply_schedule", "finops", "Apply an on and off schedule",
                ["resource_id", "schedule"], Tier.T1, "One resource",
                ("executor_confirmed", "The schedule is applied"),
                (R.REVERT, "Restore the previous schedule"),
                floor=Tier.T2,
            ),
            _contract(
                "delete_unattached_volume", "finops", "Delete an unattached volume after a snapshot",
                ["volume_id"], Tier.T2, "One volume",
                ("executor_confirmed", "The volume is gone and the snapshot exists"),
                (R.REVERT, "Restore the volume from the snapshot taken first"),
                preconditions=["The volume is not attached"],
            ),
            _contract(
                "rightsize_instance", "finops", "Change an instance size",
                ["resource_id", "new_size"], Tier.T2, "One instance",
                ("service_healthy", "The workload is healthy at the new size"),
                (R.REVERT, "Restore the previous size"),
            ),
            _contract(
                "purchase_commitment", "finops", "Purchase a reserved commitment",
                ["commitment_id", "term_months"], Tier.T3, "Financial commitment",
                ("executor_confirmed", "The purchase is recorded"),
                (R.COMPENSATE, "Commitments usually cannot be cancelled; people decide with finance"),
            ),
        ]
    )
