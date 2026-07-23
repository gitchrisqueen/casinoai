"""Conformance harness tests with a scripted (mocked) agent — no LLM calls."""

from casinoai.agents.decision_agent import AgentBet, AgentDecision
from casinoai.harness import conformance
from casinoai.rules.oracle import compile_spec
from tests.rules.test_oracle import martingale_spec


def perfect_agent(spec, history, net_units, model=None, ledger=None):
    """Replays the oracle's own decision — must score 100%."""
    shadow = compile_spec(spec)
    for r in history:
        shadow.next_action()
        from casinoai.engines.roulette import RouletteOutcome

        shadow.observe(RouletteOutcome.model_validate(r.outcome))
    action = shadow.next_action()
    return (
        AgentDecision(
            bets=[AgentBet(bet_type=b.bet_type, stake_units=b.stake_units) for b in action.bets],
            stop=action.stop,
            rationale="shadow oracle",
        ),
        0.0,
    )


def stubborn_agent(spec, history, net_units, model=None, ledger=None):
    """Always flat-bets 1 unit on red — wrong whenever the progression climbs."""
    return (
        AgentDecision(
            bets=[AgentBet(bet_type="red", stake_units=1.0)], stop=False, rationale="flat"
        ),
        0.0,
    )


def test_perfect_agent_scores_100(monkeypatch):
    monkeypatch.setattr(conformance, "decide", perfect_agent)
    report = conformance.run_conformance(martingale_spec(), model="mock", rounds=30, seed=4)
    assert report.decisions > 0
    assert report.match_rate == 1.0
    assert report.divergences == []


def test_divergences_are_recorded_with_context(monkeypatch):
    monkeypatch.setattr(conformance, "decide", stubborn_agent)
    report = conformance.run_conformance(martingale_spec(), model="mock", rounds=30, seed=4)
    assert report.match_rate < 1.0
    assert report.divergences
    d = report.divergences[0]
    assert d.expected["bets"] != d.actual["bets"] or d.expected["stop"] != d.actual["stop"]
    assert d.rationale == "flat"


def test_session_stops_when_oracle_stops(monkeypatch):
    monkeypatch.setattr(conformance, "decide", perfect_agent)
    spec = martingale_spec(bankroll={"stop_loss_units": 3, "stop_win_units": 2})
    report = conformance.run_conformance(spec, model="mock", rounds=500, seed=4)
    assert report.decisions < 500  # stopped early, and the stop decision was compared too
