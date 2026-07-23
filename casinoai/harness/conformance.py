"""Conformance harness (H2): same state stream to the LLM agent and the oracle;
every divergence recorded with full context. Target: ≥ 99% decision-match."""

from typing import Any

from pydantic import BaseModel, Field

from casinoai.agents.decision_agent import AgentBet, RoundLog, decide
from casinoai.engines.factory import make_engine, play_round
from casinoai.rules.oracle import Action, compile_spec
from casinoai.strategies.spec import StrategySpec


class Divergence(BaseModel):
    round_index: int
    expected: dict[str, Any]  # oracle action
    actual: dict[str, Any]  # agent decision
    rationale: str
    history_len: int
    net_units: float


class ConformanceReport(BaseModel):
    strategy: str
    spec_version: int
    model: str
    seed: int
    rounds: int
    decisions: int
    matches: int
    match_rate: float
    divergences: list[Divergence] = Field(default_factory=list)
    total_cost_usd: float


def _normalize(bets: list[AgentBet]) -> list[tuple[str, float]]:
    return sorted((b.bet_type, round(b.stake_units, 6)) for b in bets)


def _actions_match(oracle_action: Action, agent_bets: list[AgentBet], agent_stop: bool) -> bool:
    if oracle_action.stop != agent_stop:
        return False
    expected = sorted((b.bet_type, round(b.stake_units, 6)) for b in oracle_action.bets)
    return expected == _normalize(agent_bets)


def run_conformance(
    spec: StrategySpec,
    model: str | None,
    rounds: int,
    seed: int = 0,
) -> ConformanceReport:
    """The oracle plays the session (ground truth drives state); at every round
    the agent is asked for the same decision from the same observable state."""
    from casinoai.llm import resolve_model

    model = resolve_model(model)
    engine = make_engine(spec, seed)
    oracle = compile_spec(spec)
    history: list[RoundLog] = []
    divergences: list[Divergence] = []
    decisions = matches = 0
    total_cost = 0.0

    for round_index in range(rounds):
        oracle_action = oracle.next_action()
        agent_decision, cost = decide(spec, history, oracle.net_units, model=model)
        total_cost += cost
        decisions += 1
        if _actions_match(oracle_action, agent_decision.bets, agent_decision.stop):
            matches += 1
        else:
            divergences.append(
                Divergence(
                    round_index=round_index,
                    expected=oracle_action.model_dump(),
                    actual=agent_decision.model_dump(exclude={"rationale"}),
                    rationale=agent_decision.rationale,
                    history_len=len(history),
                    net_units=oracle.net_units,
                )
            )
        if oracle_action.stop:
            break
        outcome = play_round(engine)
        net = oracle.observe(outcome)
        history.append(
            RoundLog(
                outcome=outcome.model_dump(),
                my_bets=[
                    AgentBet(bet_type=b.bet_type, stake_units=b.stake_units)
                    for b in oracle_action.bets
                ],
                net_units=net,
            )
        )

    return ConformanceReport(
        strategy=spec.name,
        spec_version=spec.version,
        model=model,
        seed=seed,
        rounds=rounds,
        decisions=decisions,
        matches=matches,
        match_rate=matches / decisions if decisions else 0.0,
        divergences=divergences,
        total_cost_usd=total_cost,
    )
