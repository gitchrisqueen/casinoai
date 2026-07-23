"""state_view() exposes facts-level state but never the resolved stake/bet."""

from casinoai.rules.oracle import compile_spec
from tests.rules.test_minimax import minimax_spec
from tests.rules.test_power_baccarat import pb_spec


def test_minimax_state_view_has_chip_stacks_not_stake():
    from casinoai.engines.roulette import RouletteOutcome

    oracle = compile_spec(minimax_spec())
    oracle.next_action()
    oracle.observe(RouletteOutcome.from_pocket("2"))  # a loss
    view = oracle.state_view()
    prog = view["progression"]
    assert prog["kind"] == "mini_max"
    assert "chip_stacks_ABC" in prog
    assert "leftmost_nonempty_spot" in prog
    # never leaks the resolved stake or bet_type
    assert "stake" not in prog and "next_stake" not in prog
    assert view["bet_selection"]["kind"] == "iab"
    assert "directive" in view["bet_selection"]


def test_power_baccarat_state_view_tracks_mode():
    from casinoai.engines.baccarat import BaccaratEngine

    oracle = compile_spec(pb_spec())
    engine = BaccaratEngine(seed=1)
    for _ in range(6):
        a = oracle.next_action()
        if a.stop:
            break
        oracle.observe(engine.deal())
    view = oracle.state_view()
    assert view["progression"]["kind"] == "power_baccarat"
    assert view["progression"]["mode"] in ("strike", "counter", "trend")
    assert view["bet_selection"]["kind"] == "tracker"
    assert "recent_outcomes" in view


def test_ledger_facts_passes_state_to_agent(monkeypatch):
    """With ledger='facts', the harness feeds oracle.state_view() to decide()."""
    from casinoai.agents.decision_agent import AgentBet, AgentDecision
    from casinoai.harness import conformance
    from tests.rules.test_oracle import martingale_spec

    seen_ledgers = []

    def capture(spec, history, net_units, model=None, ledger=None):
        seen_ledgers.append(ledger)
        return (
            AgentDecision(
                bets=[AgentBet(bet_type="red", stake_units=1.0)], stop=False, rationale=""
            ),
            0.0,
        )

    monkeypatch.setattr(conformance, "decide", capture)
    report = conformance.run_conformance(
        martingale_spec(), model="mock", rounds=3, seed=1, ledger="facts"
    )
    assert report.ledger_mode == "facts"
    assert all(lg is not None for lg in seen_ledgers)
    assert "progression" in seen_ledgers[0]
    # realized outcomes recorded
    assert report.oracle_staked_units > 0


def test_ledger_none_sends_no_state(monkeypatch):
    from casinoai.agents.decision_agent import AgentBet, AgentDecision
    from casinoai.harness import conformance
    from tests.rules.test_oracle import martingale_spec

    seen = []

    def capture(spec, history, net_units, model=None, ledger=None):
        seen.append(ledger)
        return (
            AgentDecision(
                bets=[AgentBet(bet_type="red", stake_units=1.0)], stop=False, rationale=""
            ),
            0.0,
        )

    monkeypatch.setattr(conformance, "decide", capture)
    conformance.run_conformance(martingale_spec(), model="mock", rounds=2, seed=1, ledger="none")
    assert all(lg is None for lg in seen)
