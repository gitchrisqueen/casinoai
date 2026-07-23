"""Conformance matrix reporting: aggregates data/results/conformance-*.json
into a strategy × model match-rate table (H2 deliverable).

Pure aggregation — reads what the harness wrote.
"""

from pathlib import Path

from pydantic import BaseModel

from casinoai.harness.conformance import ConformanceReport

DEFAULT_RESULTS_DIR = Path("data/results")


class MatrixCell(BaseModel):
    strategy: str
    model: str
    decisions: int
    matches: int
    match_rate: float
    divergences: int
    cost_usd: float


def load_conformance(results_dir: Path = DEFAULT_RESULTS_DIR) -> list[ConformanceReport]:
    reports = []
    for path in sorted(results_dir.glob("conformance-*.json")):
        reports.append(ConformanceReport.model_validate_json(path.read_text()))
    return reports


def build_cells(reports: list[ConformanceReport]) -> list[MatrixCell]:
    return [
        MatrixCell(
            strategy=r.strategy,
            model=r.model,
            decisions=r.decisions,
            matches=r.matches,
            match_rate=r.match_rate,
            divergences=len(r.divergences),
            cost_usd=r.total_cost_usd,
        )
        for r in reports
    ]


def render_markdown(reports: list[ConformanceReport]) -> str:
    """A strategy × model match-rate table plus a divergence appendix. The H2
    target is >= 99% decision-match; cells report the observed rate."""
    cells = build_cells(reports)
    strategies = sorted({c.strategy for c in cells})
    models = sorted({c.model for c in cells})
    by_key = {(c.strategy, c.model): c for c in cells}

    lines = [
        "# CasinoAI H2 Conformance Matrix",
        "",
        "Decision-match rate: an LLM agent, given only the strategy spec and the "
        "session so far, vs. the deterministic oracle on the same state stream. "
        "Target >= 99%. A low rate means the model cannot reliably execute the "
        "strategy's bookkeeping (progression level, mode, bet selection).",
        "",
        "| Strategy | " + " | ".join(models) + " |",
        "|---|" + "|".join(["---"] * len(models)) + "|",
    ]
    for strat in strategies:
        row = [strat]
        for model in models:
            cell = by_key.get((strat, model))
            if cell is None:
                row.append("—")
            else:
                row.append(f"{cell.match_rate:.0%} ({cell.matches}/{cell.decisions})")
        lines.append("| " + " | ".join(row) + " |")

    # divergence appendix — the interesting failures
    diverging = [r for r in reports if r.divergences]
    if diverging:
        lines += ["", "## Divergences", ""]
        for r in diverging:
            lines.append(f"**{r.strategy} × {r.model}** ({len(r.divergences)}):")
            for d in r.divergences[:5]:
                lines.append(f"- round {d.round_index}: {d.rationale}")
            if len(r.divergences) > 5:
                lines.append(f"- ... and {len(r.divergences) - 5} more")
            lines.append("")
    return "\n".join(lines)


def write_report(
    results_dir: Path = DEFAULT_RESULTS_DIR,
    out_path: Path | None = None,
) -> Path:
    reports = load_conformance(results_dir)
    markdown = render_markdown(reports)
    out_path = out_path or results_dir / "conformance_matrix.md"
    out_path.write_text(markdown + "\n")
    return out_path
