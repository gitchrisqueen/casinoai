"""Conformance matrix reporting: aggregates data/results/conformance-*.json
into a strategy × (model, ledger) match-rate table plus realized-outcome
reporting (H2 deliverable + H3a corroboration).

Pure aggregation — reads what the harness wrote.
"""

from pathlib import Path

from pydantic import BaseModel

from casinoai.harness.conformance import ConformanceReport

DEFAULT_RESULTS_DIR = Path("data/results")


class MatrixCell(BaseModel):
    strategy: str
    model: str
    ledger: str
    decisions: int
    matches: int
    match_rate: float
    divergences: int
    cost_usd: float
    oracle_net: float
    oracle_staked: float
    agent_net: float
    agent_staked: float


def _col(model: str, ledger: str) -> str:
    short = model.split("/")[-1]
    return short if ledger == "none" else f"{short} [+facts]"


def load_conformance(results_dir: Path = DEFAULT_RESULTS_DIR) -> list[ConformanceReport]:
    reports = []
    for path in sorted(results_dir.glob("conformance-*.json")):
        reports.append(ConformanceReport.model_validate_json(path.read_text()))
    return reports


def build_cells(reports: list[ConformanceReport]) -> list[MatrixCell]:
    """One cell per (strategy, model, ledger), pooling seeds."""
    grouped: dict[tuple[str, str, str], list[ConformanceReport]] = {}
    for r in reports:
        grouped.setdefault((r.strategy, r.model, r.ledger_mode), []).append(r)

    cells = []
    for (strategy, model, ledger), group in grouped.items():
        decisions = sum(r.decisions for r in group)
        matches = sum(r.matches for r in group)
        cells.append(
            MatrixCell(
                strategy=strategy,
                model=model,
                ledger=ledger,
                decisions=decisions,
                matches=matches,
                match_rate=(matches / decisions) if decisions else 0.0,
                divergences=sum(len(r.divergences) for r in group),
                cost_usd=sum(r.total_cost_usd for r in group),
                oracle_net=sum(r.oracle_net_units for r in group),
                oracle_staked=sum(r.oracle_staked_units for r in group),
                agent_net=sum(r.agent_net_units for r in group),
                agent_staked=sum(r.agent_staked_units for r in group),
            )
        )
    return cells


def render_markdown(reports: list[ConformanceReport]) -> str:
    cells = build_cells(reports)
    strategies = sorted({c.strategy for c in cells})
    columns = sorted({(c.model, c.ledger) for c in cells}, key=lambda mc: (mc[1] != "none", mc[0]))
    by_key = {(c.strategy, c.model, c.ledger): c for c in cells}

    headers = [_col(m, lg) for m, lg in columns]
    lines = [
        "# CasinoAI H2 Conformance Matrix",
        "",
        "Decision-match rate: an LLM agent vs. the deterministic oracle on the "
        "same state stream. Target >= 99%. `[+facts]` = the agent was fed an "
        "authoritative CURRENT STATE block each round (facts-level bookkeeping) "
        "so it applies rules instead of reconstructing state from history.",
        "",
        "| Strategy | " + " | ".join(headers) + " |",
        "|---|" + "|".join(["---"] * len(headers)) + "|",
    ]
    for strat in strategies:
        row = [strat]
        for model, ledger in columns:
            cell = by_key.get((strat, model, ledger))
            row.append(f"{cell.match_rate:.0%} ({cell.matches}/{cell.decisions})" if cell else "—")
        lines.append("| " + " | ".join(row) + " |")

    # H3a corroboration — realized outcomes from the conformance runs
    realized = [c for c in cells if c.oracle_staked > 0]
    if realized:
        lines += [
            "",
            "## Realized outcomes (H3a corroboration)",
            "",
            "The oracle drives each session, so its realized EV is the strategy "
            "*played correctly* — a live-scale sample of H3a. The agent's realized "
            "EV is what the model itself achieved; it converges to the oracle's as "
            "conformance rises (a diverging model bleeds extra EV).",
            "",
            "| Strategy × model [ledger] | match | oracle EV/unit | agent EV/unit |",
            "|---|---|---|---|",
        ]
        for c in sorted(realized, key=lambda c: (c.strategy, c.ledger != "none", c.model)):
            oev = c.oracle_net / c.oracle_staked if c.oracle_staked else 0.0
            aev = c.agent_net / c.agent_staked if c.agent_staked else 0.0
            lines.append(
                f"| {c.strategy} × {_col(c.model, c.ledger)} | {c.match_rate:.0%} | "
                f"{oev:+.2%} | {aev:+.2%} |"
            )

    diverging = [r for r in reports if r.divergences]
    if diverging:
        lines += ["", "## Divergences", ""]
        for r in diverging:
            tag = _col(r.model, r.ledger_mode)
            lines.append(f"**{r.strategy} × {tag}** ({len(r.divergences)}):")
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
