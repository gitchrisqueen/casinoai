"""Parallel matrix tests — conformance is mocked, so no LLM/network."""

from casinoai.agents.decision_agent import AgentBet, AgentDecision
from casinoai.harness import conformance
from casinoai.harness.matrix import run_matrix
from casinoai.reports.conformance_matrix import build_cells, load_conformance


def flat_agent(spec, history, net_units, model=None):
    return (
        AgentDecision(bets=[AgentBet(bet_type="red", stake_units=1.0)], stop=False, rationale="x"),
        0.0,
    )


def test_run_matrix_fans_out_and_saves(tmp_path, monkeypatch):
    monkeypatch.setattr(conformance, "decide", flat_agent)
    specs = ["strategies/approved/power-pro-roulette-v2.yaml"]
    models = ["mock-a", "mock-b"]
    reports = run_matrix(specs, models, rounds=5, seeds=[0, 1], max_workers=4, results_dir=tmp_path)
    # 1 spec × 2 models × 2 seeds = 4 cells
    assert len(reports) == 4
    assert {r.model for r in reports} == {"mock-a", "mock-b"}
    # each cell saved a file
    assert len(list(tmp_path.glob("conformance-*.json"))) == 4


def test_matrix_reports_aggregate_seeds(tmp_path, monkeypatch):
    monkeypatch.setattr(conformance, "decide", flat_agent)
    run_matrix(
        ["strategies/approved/power-pro-roulette-v2.yaml"],
        ["mock-a"],
        rounds=5,
        seeds=[0, 1, 2],
        max_workers=3,
        results_dir=tmp_path,
    )
    reports = load_conformance(tmp_path)
    cells = build_cells(reports)
    # 3 seed files collapse to ONE (strategy, model) cell with pooled decisions
    assert len(cells) == 1
    assert cells[0].decisions == sum(r.decisions for r in reports)


def test_matrix_survives_a_failing_cell(tmp_path, monkeypatch):
    def sometimes_boom(spec, history, net_units, model=None):
        if model == "boom":
            raise RuntimeError("provider down")
        return flat_agent(spec, history, net_units, model)

    monkeypatch.setattr(conformance, "decide", sometimes_boom)
    seen = []
    reports = run_matrix(
        ["strategies/approved/power-pro-roulette-v2.yaml"],
        ["mock-a", "boom"],
        rounds=4,
        seeds=[0],
        max_workers=2,
        results_dir=tmp_path,
        on_done=lambda r, e: seen.append((r, e)),
    )
    # the good cell still completes; the bad one is reported, not fatal
    assert len(reports) == 1
    assert any(e is not None for _, e in seen)
