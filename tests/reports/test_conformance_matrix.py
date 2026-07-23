"""Conformance-matrix aggregation tests."""

from casinoai.harness.conformance import ConformanceReport, Divergence
from casinoai.reports.conformance_matrix import build_cells, render_markdown


def _report(strategy, model, matches, decisions, divs=0, ledger="none"):
    return ConformanceReport(
        strategy=strategy,
        spec_version=2,
        model=model,
        seed=7,
        rounds=decisions,
        decisions=decisions,
        matches=matches,
        match_rate=matches / decisions,
        ledger_mode=ledger,
        divergences=[
            Divergence(
                round_index=i,
                expected={"bets": []},
                actual={"bets": []},
                rationale=f"reason {i}",
                history_len=i,
                net_units=0.0,
            )
            for i in range(divs)
        ],
        total_cost_usd=0.01,
    )


def test_build_cells():
    reports = [_report("A", "kimi", 30, 30), _report("A", "gpt", 25, 30, divs=5)]
    cells = build_cells(reports)
    assert cells[0].match_rate == 1.0
    assert cells[1].divergences == 5


def test_render_markdown_matrix_and_divergences():
    reports = [
        _report("Alpha", "kimi", 30, 30),
        _report("Alpha", "gpt", 27, 30, divs=3),
        _report("Beta", "kimi", 20, 20),
    ]
    md = render_markdown(reports)
    assert "Alpha" in md and "Beta" in md
    assert "100% (30/30)" in md
    assert "90% (27/30)" in md
    assert "—" in md  # Beta × gpt missing
    assert "## Divergences" in md
    assert "reason 0" in md


def test_ledger_modes_are_distinct_columns():
    reports = [
        _report("Alpha", "gpt", 20, 30, ledger="none"),
        _report("Alpha", "gpt", 28, 30, ledger="facts"),
    ]
    cells = build_cells(reports)
    # same strategy+model but different ledger → two cells
    assert len(cells) == 2
    md = render_markdown(reports)
    assert "gpt [+facts]" in md
    assert "67% (20/30)" in md  # none
    assert "93% (28/30)" in md  # facts
