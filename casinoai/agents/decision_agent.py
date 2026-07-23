"""LLM decision agent: plays a strategy from its spec, one round at a time (H2).

The agent sees exactly what a human player would: the strategy rules, the
outcome history, its own past bets and results, and session P/L. It must NOT
see the oracle. Every decision is one gateway call returning a structured
AgentDecision.
"""

import json
from typing import Any

import yaml
from pydantic import BaseModel, Field

from casinoai.llm import complete
from casinoai.strategies.spec import StrategySpec

AGENT_SYSTEM = """\
You are a disciplined casino player executing a betting strategy EXACTLY as
specified. You never improvise, never chase losses beyond the rules, and never
deviate from the spec. Given the strategy and the session so far, decide the
bets for the next round (or stop if the rules say to stop).

Stakes are in units. Follow the progression rules precisely from the history
of your own wins and losses. If entry conditions are not met, bet nothing
(empty bets list).
"""

LEDGER_SYSTEM = """\

CURRENT STATE is provided below and is AUTHORITATIVE. It ALREADY reflects every
past outcome, including the most recent round — it is the exact state to bet
FROM right now. Do NOT re-apply the last round's win/loss transition; the level
indices, mode, and counters shown are already advanced/reset for it. Trust this
completely over any count you might reconstruct from the history.

Your only job is to APPLY the strategy's rules to this current state:
- read the current mode and level index, and map it to the correct stake using
  the spec's bet series/formula (do NOT advance the index first);
- follow the selection directive to pick the bet;
- honor entry/stop conditions.
Indices are 0-based unless stated otherwise.
"""


class AgentBet(BaseModel):
    bet_type: str
    stake_units: float


class AgentDecision(BaseModel):
    bets: list[AgentBet] = Field(default_factory=list)
    stop: bool = False
    rationale: str = Field(description="One short sentence: why this action follows the rules")


class RoundLog(BaseModel):
    """What the agent is allowed to know about one past round."""

    outcome: dict[str, Any]
    my_bets: list[AgentBet]
    net_units: float


def decide(
    spec: StrategySpec,
    history: list[RoundLog],
    net_units: float,
    model: str | None = None,
    ledger: dict | None = None,
) -> tuple[AgentDecision, float]:
    """One agent decision; returns (decision, cost_usd). When `ledger` is given
    (facts mode), an authoritative CURRENT STATE block is added and the agent is
    told to trust it over its own count."""
    spec_yaml = yaml.safe_dump(
        spec.model_dump(mode="json", exclude={"source", "approval", "ambiguities"}),
        sort_keys=False,
    )
    lines = [f"STRATEGY SPEC:\n{spec_yaml}", f"SESSION P/L: {net_units:+.2f} units"]
    if history:
        lines.append("SESSION HISTORY (oldest first):")
        for i, r in enumerate(history, 1):
            bets = ", ".join(f"{b.bet_type}@{b.stake_units:g}" for b in r.my_bets) or "no bet"
            lines.append(
                f"  round {i}: outcome={r.outcome} | my bets: {bets} | net {r.net_units:+g}"
            )
    else:
        lines.append("SESSION HISTORY: none — this is the first round.")
    if ledger is not None:
        lines.append(
            "CURRENT STATE (authoritative — apply the rules to this, do not recount):\n"
            + json.dumps(ledger, indent=2)
        )
    lines.append("Decide the next round's action.")

    result = complete(
        "\n".join(lines),
        model=model,
        system=AGENT_SYSTEM + (LEDGER_SYSTEM if ledger is not None else ""),
        schema=AgentDecision,
        tag=f"conform:{spec.name}",
    )
    return result.parsed, result.cost_usd
