"""Risk engine: the tier of a plan from its contracts, the environment and the blast radius."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .catalog import Catalog
from .models import ActionContract, Recommendation, Tier, TierT


class RiskAssessment(BaseModel):
    tier: TierT
    reasons: list[str] = Field(default_factory=list)


def assess_step(contract: ActionContract, environment: str, params: dict[str, Any]) -> tuple[Tier, list[str]]:
    tier = contract.tier
    reasons = [f"{contract.action_id}: base tier {tier.name}"]
    if environment == "prod" and contract.production_floor is not None and contract.production_floor > tier:
        tier = contract.production_floor
        reasons.append(f"{contract.action_id}: production raises it to {tier.name}")
    if contract.blast_param and contract.blast_limit is not None:
        value = params.get(contract.blast_param)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > contract.blast_limit:
            tier = Tier(min(tier + 1, Tier.T3))
            reasons.append(
                f"{contract.action_id}: {contract.blast_param}={value} is above {contract.blast_limit}, "
                f"raised to {tier.name}"
            )
    return tier, reasons


def assess(rec: Recommendation, catalog: Catalog) -> RiskAssessment:
    """The plan tier is the highest tier of any step."""
    overall = Tier.T0
    reasons: list[str] = []
    for step in rec.steps:
        tier, step_reasons = assess_step(catalog.require(step.action_id), rec.environment, step.params)
        overall = max(overall, tier)
        reasons.extend(step_reasons)
    reasons.append(f"plan tier is {overall.name}")
    return RiskAssessment(tier=overall, reasons=reasons)
