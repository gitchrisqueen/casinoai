"""Live conformance smoke (H2 preview): tiny run, real model.

Skipped by default; run with: uv run pytest -m llm tests/harness
Uses the default model (cloud Kimi if OLLAMA_API_KEY is set). This measures —
it does not assert a high match rate; that's what the full H2 runs are for.
"""

import os

import pytest

from casinoai.harness.conformance import run_conformance
from tests.rules.test_oracle import martingale_spec

pytestmark = pytest.mark.llm


@pytest.mark.skipif(not os.environ.get("OLLAMA_API_KEY"), reason="no OLLAMA_API_KEY")
def test_conformance_smoke_runs_and_reports():
    report = run_conformance(
        martingale_spec(), model="ollama-cloud/kimi-k2.6:cloud", rounds=5, seed=1
    )
    assert report.decisions == 5 or report.decisions < 5  # stop may end it early
    assert 0.0 <= report.match_rate <= 1.0
    print(
        f"\nconformance smoke: {report.matches}/{report.decisions} matched "
        f"({report.match_rate:.0%}), cost ${report.total_cost_usd:.4f}"
    )
