"""Cross-strategy reporting: leaderboard + markdown/HTML summary from the
backtest JSON files in data/results/ (Phase 5 exit criterion, Phase 7 input).

Pure aggregation — no LLM, no simulation. Reads what the backtester wrote.
"""

from pathlib import Path

from pydantic import BaseModel

from casinoai.backtest.runner import BacktestSummary

DEFAULT_RESULTS_DIR = Path("data/results")


class LeaderboardRow(BaseModel):
    strategy: str
    version: int
    game: str
    sessions: int
    total_rounds: int
    ev_per_unit_staked: float
    session_win_rate: float
    mean_session_net: float
    stdev_session_net: float
    worst_drawdown_units: float
    risk_of_ruin: float
    git_sha: str | None


def load_backtests(results_dir: Path = DEFAULT_RESULTS_DIR) -> list[BacktestSummary]:
    summaries = []
    for path in sorted(results_dir.glob("backtest-*.json")):
        summaries.append(BacktestSummary.model_validate_json(path.read_text()))
    return summaries


def build_leaderboard(summaries: list[BacktestSummary]) -> list[LeaderboardRow]:
    """Rank by EV per unit staked, best (least negative) first."""
    rows = [
        LeaderboardRow(
            strategy=s.strategy,
            version=s.spec_version,
            game=s.game,
            sessions=s.n_sessions,
            total_rounds=s.total_rounds,
            ev_per_unit_staked=s.ev_per_unit_staked,
            session_win_rate=s.session_win_rate,
            mean_session_net=s.mean_session_net,
            stdev_session_net=s.stdev_session_net,
            worst_drawdown_units=s.worst_drawdown_units,
            risk_of_ruin=s.risk_of_ruin,
            git_sha=s.git_sha,
        )
        for s in summaries
    ]
    return sorted(rows, key=lambda r: r.ev_per_unit_staked, reverse=True)


def render_markdown(rows: list[LeaderboardRow]) -> str:
    """A markdown leaderboard. EV per unit staked is the honest headline metric;
    session win rate is included precisely because it is the misleading one the
    books advertise."""
    lines = [
        "# CasinoAI Strategy Leaderboard",
        "",
        "Backtested betting systems, ranked by EV per unit staked (the honest "
        "measure). Every system tested loses to the house edge; a high session "
        "win rate just means many small wins funding rare large losses.",
        "",
        "| Rank | Strategy | Game | EV/unit | Session win rate | Mean/session | "
        "Worst drawdown | Risk of ruin | Sessions |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(rows, 1):
        lines.append(
            f"| {i} | {r.strategy} v{r.version} | {r.game} | "
            f"{r.ev_per_unit_staked:+.2%} | {r.session_win_rate:.1%} | "
            f"{r.mean_session_net:+.1f}u | {r.worst_drawdown_units:.0f}u | "
            f"{r.risk_of_ruin:.1%} | {r.sessions:,} |"
        )
    lines += [
        "",
        f"_{len(rows)} strategies, {sum(r.total_rounds for r in rows):,} total simulated rounds._",
    ]
    return "\n".join(lines)


def write_report(
    results_dir: Path = DEFAULT_RESULTS_DIR,
    out_path: Path | None = None,
) -> Path:
    summaries = load_backtests(results_dir)
    rows = build_leaderboard(summaries)
    markdown = render_markdown(rows)
    out_path = out_path or results_dir / "leaderboard.md"
    out_path.write_text(markdown + "\n")
    return out_path
