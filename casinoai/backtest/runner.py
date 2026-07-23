"""Monte Carlo backtester: runs the *oracle* (never the LLM) for H3a.

Reproducibility is a feature under test: every run records seeds, spec
version, and git SHA. Same spec + same seeds → identical results, forever.
"""

import statistics
import subprocess
from pathlib import Path

from pydantic import BaseModel

from casinoai.engines.factory import make_engine, play_round
from casinoai.rules.oracle import compile_spec
from casinoai.strategies.spec import StrategySpec

DEFAULT_RESULTS_DIR = Path("data/results")


class SessionResult(BaseModel):
    seed: int
    rounds_played: int
    net_units: float
    total_staked_units: float
    max_drawdown_units: float
    stop_reason: str | None


class BacktestSummary(BaseModel):
    strategy: str
    spec_version: int
    game: str
    git_sha: str | None
    seeds: list[int]
    max_rounds_per_session: int
    n_sessions: int
    total_rounds: int
    total_staked_units: float
    total_net_units: float
    ev_per_unit_staked: float
    session_win_rate: float
    mean_session_net: float
    stdev_session_net: float
    worst_drawdown_units: float
    risk_of_ruin: float  # fraction of sessions ending on stop-loss / bankroll exhaustion
    sessions: list[SessionResult]


def run_session(spec: StrategySpec, seed: int, max_rounds: int) -> SessionResult:
    engine = make_engine(spec, seed)
    oracle = compile_spec(spec)
    peak = 0.0
    max_dd = 0.0
    staked = 0.0
    for _ in range(max_rounds):
        action = oracle.next_action()
        if action.stop:
            break
        staked += sum(b.stake_units for b in action.bets)
        oracle.observe(play_round(engine))
        peak = max(peak, oracle.net_units)
        max_dd = max(max_dd, peak - oracle.net_units)
    return SessionResult(
        seed=seed,
        rounds_played=oracle.rounds_played,
        net_units=oracle.net_units,
        total_staked_units=staked,
        max_drawdown_units=max_dd,
        stop_reason=oracle.stopped,
    )


def _git_sha() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def backtest(spec: StrategySpec, seeds: list[int], max_rounds: int) -> BacktestSummary:
    sessions = [run_session(spec, seed, max_rounds) for seed in seeds]
    nets = [s.net_units for s in sessions]
    total_staked = sum(s.total_staked_units for s in sessions)
    total_net = sum(nets)
    ruinous = sum(
        1
        for s in sessions
        if s.stop_reason and ("stop-loss" in s.stop_reason or "exhausted" in s.stop_reason)
    )
    return BacktestSummary(
        strategy=spec.name,
        spec_version=spec.version,
        game=spec.game.value,
        git_sha=_git_sha(),
        seeds=seeds,
        max_rounds_per_session=max_rounds,
        n_sessions=len(sessions),
        total_rounds=sum(s.rounds_played for s in sessions),
        total_staked_units=total_staked,
        total_net_units=total_net,
        ev_per_unit_staked=(total_net / total_staked) if total_staked else 0.0,
        session_win_rate=sum(1 for n in nets if n > 0) / len(sessions),
        mean_session_net=statistics.mean(nets),
        stdev_session_net=statistics.stdev(nets) if len(nets) > 1 else 0.0,
        worst_drawdown_units=max(s.max_drawdown_units for s in sessions),
        risk_of_ruin=ruinous / len(sessions),
        sessions=sessions,
    )


def save_summary(summary: BacktestSummary, results_dir: Path = DEFAULT_RESULTS_DIR) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    slug = summary.strategy.lower().replace(" ", "-")
    path = results_dir / f"backtest-{slug}-v{summary.spec_version}.json"
    path.write_text(summary.model_dump_json(indent=2))
    return path
