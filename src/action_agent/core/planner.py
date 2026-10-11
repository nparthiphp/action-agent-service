"""Planner interface and the deterministic plan validator.

v1 has no LLM: ARIES sends structured steps, so the planner passes them through. A planner that
uses an LLM (for example one built on Microsoft Agent Framework) can implement ``Planner`` later.
Whatever it proposes still goes through ``validate_plan``, the policy check and the risk tier, so a
model can propose steps but never bypass the controls.
"""
from __future__ import annotations

import re
from typing import Protocol

from .catalog import Catalog
from .models import Recommendation

PLACEHOLDER = re.compile(r"^\$step\[(\d+)\]\.([A-Za-z_]\w*)$")


class Planner(Protocol):
    def plan(self, rec: Recommendation) -> Recommendation: ...


class PassthroughPlanner:
    def plan(self, rec: Recommendation) -> Recommendation:
        return rec


def validate_plan(rec: Recommendation, catalog: Catalog) -> list[str]:
    errors: list[str] = []
    for index, step in enumerate(rec.steps):
        contract = catalog.get(step.action_id)
        if contract is None:
            errors.append(f"step {index}: unknown action '{step.action_id}'")
            continue
        for name in contract.inputs:
            if name not in step.params:
                errors.append(f"step {index}: missing input '{name}' for {step.action_id}")
        for key, value in step.params.items():
            if isinstance(value, str):
                match = PLACEHOLDER.match(value)
                if match and int(match.group(1)) >= index:
                    errors.append(
                        f"step {index}: '{key}' refers to step {match.group(1)}, which does not run before it"
                    )
    return errors
