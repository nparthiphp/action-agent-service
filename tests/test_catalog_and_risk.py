import pytest
from pydantic import ValidationError

from action_agent.core.autonomy import Disposition, Mode, decide, effective_mode
from action_agent.core.catalog import Catalog, default_catalog
from action_agent.core.models import ActionContract, RollbackKind, RollbackSpec, Tier, VerifySpec
from action_agent.core.planner import validate_plan
from action_agent.core.risk import assess
from action_agent.executors.finops.app import FinOpsExecutor
from action_agent.executors.incident.app import IncidentExecutor
from action_agent.executors.infra.app import InfraExecutor

from helpers import TICKET, rec

EXECUTORS = {"incident": IncidentExecutor, "infra": InfraExecutor, "finops": FinOpsExecutor}


def test_catalog_covers_three_domains_with_unique_actions():
    catalog = default_catalog()
    assert catalog.domains() == ["finops", "incident", "infra"]
    assert len({c.action_id for c in catalog.all()}) == len(catalog.all())


def test_every_action_has_verify_and_rollback_declared():
    for contract in default_catalog().all():
        assert contract.verify.description
        assert contract.rollback.description


def test_every_non_t3_action_has_a_handler_and_t3_has_none():
    catalog = default_catalog()
    for contract in catalog.all():
        handled = contract.action_id in EXECUTORS[contract.domain]().action_ids
        assert handled == (contract.tier < Tier.T3), contract.action_id


def test_rollback_none_is_rejected_for_t2_and_above():
    with pytest.raises(ValidationError):
        ActionContract(
            action_id="x", domain="infra", summary="x", blast_radius="x", tier=Tier.T2,
            verify=VerifySpec(check="executor_confirmed", description="x"),
            rollback=RollbackSpec(kind=RollbackKind.NONE, description="x"),
        )


def test_duplicate_actions_are_rejected():
    contract = default_catalog().require("create_ticket")
    with pytest.raises(ValueError):
        Catalog([contract, contract])


def test_production_raises_low_tier_actions():
    catalog = default_catalog()
    step = [("stop_idle_resource", {"resource_id": "vm-dev-01"})]
    assert assess(rec(step, environment="nonprod"), catalog).tier == Tier.T1
    assert assess(rec(step, environment="prod"), catalog).tier == Tier.T2


def test_large_blast_radius_raises_the_tier():
    catalog = default_catalog()
    small = rec([("scale_node_group", {"group": "payments-ng", "desired": 5})])
    large = rec([("scale_node_group", {"group": "payments-ng", "desired": 12})])
    assert assess(small, catalog).tier == Tier.T2
    assert assess(large, catalog).tier == Tier.T3


def test_plan_tier_is_the_highest_step_tier():
    catalog = default_catalog()
    plan = rec([TICKET, ("extend_disk", {"host": "web-01", "volume": "/data", "new_size_gb": 200})])
    assert assess(plan, catalog).tier == Tier.T2


def test_decide_follows_the_trust_ladder():
    assert decide(Tier.T1, Mode.SHADOW) is Disposition.SHADOW_ONLY
    assert decide(Tier.T1, Mode.SUGGEST) is Disposition.HUMAN_EXECUTES
    assert decide(Tier.T0, Mode.APPROVE_AND_RUN) is Disposition.AUTO
    assert decide(Tier.T1, Mode.APPROVE_AND_RUN) is Disposition.NEEDS_APPROVAL
    assert decide(Tier.T1, Mode.AUTO_T1) is Disposition.AUTO
    assert decide(Tier.T2, Mode.AUTO_T1) is Disposition.NEEDS_APPROVAL
    assert decide(Tier.T3, Mode.AUTO_T1) is Disposition.HUMAN_EXECUTES


def test_most_restrictive_mode_wins():
    modes = {"restart_service": Mode.SUGGEST}
    assert effective_mode(modes, Mode.AUTO_T1, ["create_ticket", "restart_service"]) is Mode.SUGGEST


def test_validate_plan_catches_unknown_missing_and_forward_references():
    catalog = default_catalog()
    assert validate_plan(rec([("nope", {})]), catalog)
    assert validate_plan(rec([("create_ticket", {"title": "x"})]), catalog)
    forward = rec([("update_ticket", {"ticket_id": "$step[0].ticket_id", "note": "x"})])
    assert validate_plan(forward, catalog)
    ok = rec([TICKET, ("update_ticket", {"ticket_id": "$step[0].ticket_id", "note": "x"})])
    assert validate_plan(ok, catalog) == []
