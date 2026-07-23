"""Live-session tracking: join recorded demo sessions to the strategy's backtest
and its promoter claim, so one table shows claimed vs. simulated vs. observed.

This is the H3b + Phase 8 deliverable for a single strategy: does live/demo play
land where the Monte Carlo predicted, and how does either compare to the hype?
"""

from pathlib import Path

from pydantic import BaseModel

from casinoai.backtest.runner import BacktestSummary
from casinoai.live.compare import compare
from casinoai.live.session import LiveSession, load_sessions


class StrategyTracking(BaseModel):
    strategy: str
    # claimed
    claimed_win_rate: float | None = None
    claimed_summary: str | None = None
    # simulated (backtest)
    sim_ev_per_unit: float | None = None
    sim_session_win_rate: float | None = None
    # observed (live/demo)
    live_sessions: int = 0
    live_rounds: int = 0
    live_ev_per_unit: float | None = None
    live_session_win_rate: float | None = None
    consistency_note: str = ""


def _sessions_for(strategy: str, sessions: list[LiveSession]) -> list[LiveSession]:
    return [s for s in sessions if s.strategy == strategy]


def build_tracking(
    strategy: str,
    backtest: BacktestSummary | None = None,
    claim=None,
    sessions_dir: Path | None = None,
) -> StrategyTracking:
    sessions = _sessions_for(
        strategy, load_sessions(sessions_dir) if sessions_dir else load_sessions()
    )
    t = StrategyTracking(strategy=strategy)
    if claim is not None:
        t.claimed_win_rate = claim.claimed.win_rate
        bits = []
        if claim.claimed.win_rate is not None:
            bits.append(f"{claim.claimed.win_rate:.0%} win")
        if claim.claimed.beats_house_edge:
            bits.append("beats house")
        if claim.claimed.guaranteed:
            bits.append("guaranteed")
        t.claimed_summary = ", ".join(bits) or None
    if backtest is not None:
        t.sim_ev_per_unit = backtest.ev_per_unit_staked
        t.sim_session_win_rate = backtest.session_win_rate
    if sessions:
        t.live_sessions = len(sessions)
        t.live_rounds = sum(len(s.rounds) for s in sessions)
        won = sum(1 for s in sessions if s.net_units > 0)
        t.live_session_win_rate = won / len(sessions)
        if backtest is not None:
            cmp = compare(sessions, backtest)
            t.live_ev_per_unit = cmp.live_ev_per_unit_staked
            t.consistency_note = cmp.note
    else:
        t.consistency_note = "no live sessions recorded yet — run `casinoai live`"
    return t


def render_tracking(rows: list[StrategyTracking]) -> str:
    lines = [
        "# CasinoAI Strategy Tracking — claimed vs. simulated vs. live",
        "",
        "| Strategy | Claimed | Sim EV/unit | Sim win rate | Live sessions | "
        "Live EV/unit | Live win rate |",
        "|---|---|---|---|---|---|---|",
    ]
    for t in rows:
        sim_ev = f"{t.sim_ev_per_unit:+.2%}" if t.sim_ev_per_unit is not None else "—"
        sim_wr = f"{t.sim_session_win_rate:.0%}" if t.sim_session_win_rate is not None else "—"
        live_ev = f"{t.live_ev_per_unit:+.2%}" if t.live_ev_per_unit is not None else "—"
        live_wr = f"{t.live_session_win_rate:.0%}" if t.live_session_win_rate is not None else "—"
        lines.append(
            f"| {t.strategy} | {t.claimed_summary or '—'} | {sim_ev} | {sim_wr} | "
            f"{t.live_sessions} | {live_ev} | {live_wr} |"
        )
    notes = [f"- **{t.strategy}:** {t.consistency_note}" for t in rows if t.consistency_note]
    if notes:
        lines += ["", "### Notes", *notes]
    return "\n".join(lines)
