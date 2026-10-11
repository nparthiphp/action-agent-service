"""Trust ladder: how much the agent may do on its own, per action."""
from __future__ import annotations

from enum import Enum
from typing import Iterable, Mapping

from .models import Tier


class Mode(str, Enum):
    SHADOW = "shadow"  # plan and record, execute nothing
    SUGGEST = "suggest"  # hand the plan to a person, who acts
    APPROVE_AND_RUN = "approve_and_run"  # a person approves, the agent runs (read-only runs by itself)
    AUTO_T1 = "auto_t1"  # T0 and T1 run by themselves, T2 needs approval


class Disposition(str, Enum):
    SHADOW_ONLY = "shadow_only"
    HUMAN_EXECUTES = "human_executes"
    NEEDS_APPROVAL = "needs_approval"
    AUTO = "auto"


# From most to least restrictive.
_ORDER = [Mode.SHADOW, Mode.SUGGEST, Mode.APPROVE_AND_RUN, Mode.AUTO_T1]


def effective_mode(modes: Mapping[str, Mode], default: Mode, action_ids: Iterable[str]) -> Mode:
    """A plan runs in the most restrictive mode of any of its actions."""
    chosen = [modes.get(action_id, default) for action_id in action_ids]
    return min(chosen, key=_ORDER.index)


def decide(tier: Tier, mode: Mode) -> Disposition:
    if mode is Mode.SHADOW:
        return Disposition.SHADOW_ONLY
    if tier >= Tier.T3:
        return Disposition.HUMAN_EXECUTES
    if mode is Mode.SUGGEST:
        return Disposition.HUMAN_EXECUTES
    if mode is Mode.APPROVE_AND_RUN:
        return Disposition.AUTO if tier == Tier.T0 else Disposition.NEEDS_APPROVAL
    return Disposition.AUTO if tier <= Tier.T1 else Disposition.NEEDS_APPROVAL
