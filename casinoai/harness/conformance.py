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
    ledger_mode: str = "none"
    divergences: list[Divergence] = Field(default_factory=list)
    total_cost_usd: float
    # realized outcomes: the strategy played correctly (oracle) is an H3a sample;
    # the agent's own realized play converges to it as conformance rises.
    oracle_net_units: float = 0.0
    oracle_staked_units: float = 0.0
    oracle_ev_per_unit: float = 0.0
    agent_net_units: float = 0.0
    agent_staked_units: float = 0.0
    agent_ev_per_unit: float = 0.0


def _normalize(bets: list[AgentBet]) -> list[tuple[str, float]]:
    return sorted((b.bet_type, round(b.stake_units, 6)) for b in bets)


def _actions_match(oracle_action: Action, agent_bets: list[AgentBet], agent_stop: bool) -> bool:
    if oracle_action.stop != agent_stop:
        return False
    expected = sorted((b.bet_type, round(b.stake_units, 6)) for b in oracle_action.bets)
    return expected == _normalize(agent_bets)


def _settle_agent(oracle, bets: list[AgentBet], outcome) -> tuple[float, float]:
    """The agent's realized (net, staked) for its own bets this round. An
    unknown/invalid bet type counts as a lost wager (it couldn't be placed)."""
    net = staked = 0.0
    for b in bets:
        staked += b.stake_units
        try:
            net += oracle.settle(b.bet_type, b.stake_units, outcome)
        except (ValueError, KeyError):
            net -= b.stake_units
    return net, staked


def run_conformance(
    spec: StrategySpec,
    model: str | None,
    rounds: int,
    seed: int = 0,
    ledger: str = "none",
) -> ConformanceReport:
    """The oracle plays the session (ground truth drives state); at every round
    the agent is asked for the same decision from the same observable state.
    `ledger`: "none" (agent recounts from history) or "facts" (an authoritative
    state block is fed back). Records both the oracle's realized outcome (the
    strategy played correctly — an H3a sample) and the agent's own realized play."""
    from casinoai.llm import resolve_model

    model = resolve_model(model)
    engine = make_engine(spec, seed)
    oracle = compile_spec(spec)
    history: list[RoundLog] = []
    divergences: list[Divergence] = []
    decisions = matches = 0
    total_cost = 0.0
    oracle_net = oracle_staked = 0.0
    agent_net = agent_staked = 0.0

    for round_index in range(rounds):
        oracle_action = oracle.next_action()
        ledger_view = oracle.state_view() if ledger == "facts" else None
        agent_decision, cost = decide(
            spec, history, oracle.net_units, model=model, ledger=ledger_view
        )
        total_cost += cost
        decisions += 1
        if _actions_match(oracle_action, agent_decision.bets, agent_decision.stop):
            matches += 1
        else:
            divergences.append(
                Divergence(
                    round_index=round_index,
                    expected=oracle_action.model_dump(),
                    actual=agent_decision.model_dump(exclude={"rationale", "computation"}),
                    rationale=agent_decision.computation or agent_decision.rationale,
                    history_len=len(history),
                    net_units=oracle.net_units,
                )
            )
        if oracle_action.stop:
            break
        outcome = play_round(engine)
        # agent's own realized play (settled against the same outcome)
        a_net, a_staked = _settle_agent(oracle, agent_decision.bets, outcome)
        agent_net += a_net
        agent_staked += a_staked
        oracle_staked += sum(b.stake_units for b in oracle_action.bets)
        net = oracle.observe(outcome)
        oracle_net += net
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
        ledger_mode=ledger,
        divergences=divergences,
        total_cost_usd=total_cost,
        oracle_net_units=oracle_net,
        oracle_staked_units=oracle_staked,
        oracle_ev_per_unit=(oracle_net / oracle_staked) if oracle_staked else 0.0,
        agent_net_units=agent_net,
        agent_staked_units=agent_staked,
        agent_ev_per_unit=(agent_net / agent_staked) if agent_staked else 0.0,
    )
