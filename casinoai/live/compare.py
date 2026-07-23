"""Observed (live/demo) vs. simulated (Monte Carlo) comparison — the H3b test.

Given recorded live sessions and the strategy's backtest, ask: does live play
land where the simulation predicted? Compares per-round EV and per-session net
against the simulated distribution. Small live samples are noisy — the report
states the observed values with their simulated reference, not a verdict.
"""

import statistics

from pydantic import BaseModel

from casinoai.backtest.runner import BacktestSummary
from casinoai.live.session import LiveSession


class LiveVsSim(BaseModel):
    strategy: str
    live_sessions: int
    live_rounds: int
    live_total_staked_units: float
    live_net_units: float
    live_ev_per_unit_staked: float
    live_mean_session_net: float
    sim_ev_per_unit_staked: float
    sim_mean_session_net: float
    sim_stdev_session_net: float
    # how many simulated session-net standard deviations the live mean sits from sim mean
    z_score: float | None
    within_2_sigma: bool | None
    note: str


def _session_staked(session: LiveSession) -> float:
    return sum(b["stake_units"] for r in session.rounds for b in r.bets)


def compare(sessions: list[LiveSession], backtest: BacktestSummary) -> LiveVsSim:
    if not sessions:
        raise ValueError("no live sessions to compare")
    live_nets = [s.net_units for s in sessions]
    live_staked = sum(_session_staked(s) for s in sessions)
    live_net = sum(live_nets)
    live_rounds = sum(len(s.rounds) for s in sessions)
    live_mean = statistics.mean(live_nets)

    sim_sd = backtest.stdev_session_net
    n = len(sessions)
    # standard error of the live mean under the simulated per-session variance
    if sim_sd > 0 and n > 0:
        se = sim_sd / (n**0.5)
        z = (live_mean - backtest.mean_session_net) / se
        within = abs(z) <= 2.0
    else:
        z = None
        within = None

    if n < 10:
        note = (
            f"Only {n} live session(s): treat as directional, not conclusive. "
            "Phase 6 exit criterion is >= 10 recorded sessions."
        )
    elif within:
        note = "Live results are consistent with the Monte Carlo prediction (within 2 sigma)."
    else:
        note = "Live results deviate from the Monte Carlo prediction by more than 2 sigma."

    return LiveVsSim(
        strategy=backtest.strategy,
        live_sessions=n,
        live_rounds=live_rounds,
        live_total_staked_units=live_staked,
        live_net_units=live_net,
        live_ev_per_unit_staked=(live_net / live_staked) if live_staked else 0.0,
        live_mean_session_net=live_mean,
        sim_ev_per_unit_staked=backtest.ev_per_unit_staked,
        sim_mean_session_net=backtest.mean_session_net,
        sim_stdev_session_net=sim_sd,
        z_score=z,
        within_2_sigma=within,
        note=note,
    )


def render_markdown(cmp: LiveVsSim) -> str:
    lines = [
        f"# Live vs. Simulated — {cmp.strategy}",
        "",
        "| Metric | Live (demo) | Simulated |",
        "|---|---|---|",
        f"| EV per unit staked | {cmp.live_ev_per_unit_staked:+.2%} | "
        f"{cmp.sim_ev_per_unit_staked:+.2%} |",
        f"| Mean session net | {cmp.live_mean_session_net:+.1f}u | "
        f"{cmp.sim_mean_session_net:+.1f}u |",
        f"| Sessions | {cmp.live_sessions} | {cmp.sim_stdev_session_net:.1f}u σ |",
        f"| Live rounds | {cmp.live_rounds} | — |",
    ]
    if cmp.z_score is not None:
        lines.append(f"| z-score | {cmp.z_score:+.2f} | (|z|≤2 = consistent) |")
    lines += ["", cmp.note]
    return "\n".join(lines)
