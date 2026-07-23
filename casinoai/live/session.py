"""The guarded live/demo session loop (Phase 6, H3b).

Drives the deterministic oracle (the proven-conformant strategy) against a live
demo table: decide bets → guard → place → read the spin → settle → record.
Emits the same RouletteOutcome the engines do. Every safety limit is enforced
by SessionGuard, independent of the spec. Human-initiated: construct with a
real reader/placer only from an operator entry point.
"""

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from casinoai.live.guard import GuardViolation, SessionGuard, SessionLimits
from casinoai.live.reader import BetPlacer, TableReader
from casinoai.rules.oracle import compile_spec
from casinoai.strategies.spec import StrategySpec

DEFAULT_SESSIONS_DIR = Path("data/results/live")


def _outcome_token(outcome) -> str:
    """Compact record of one observed outcome, across games."""
    if hasattr(outcome, "pocket"):  # roulette
        return outcome.pocket
    if hasattr(outcome, "winner"):  # baccarat
        return outcome.winner.value
    if hasattr(outcome, "result"):  # craps
        return outcome.result.value
    return str(outcome)


class RecordedRound(BaseModel):
    round_index: int
    outcome: str
    bets: list[dict]  # [{bet_type, stake_units}]
    net_units: float
    cumulative_units: float


class LiveSession(BaseModel):
    strategy: str
    spec_version: int
    table_url: str | None
    is_demo: bool
    started_at: str
    ended_at: str | None = None
    rounds: list[RecordedRound] = Field(default_factory=list)
    net_units: float = 0.0
    stop_reason: str | None = None
    limits: SessionLimits


def run_live_session(
    spec: StrategySpec,
    reader: TableReader,
    placer: BetPlacer,
    limits: SessionLimits,
    table_url: str | None = None,
    now: str | None = None,
) -> LiveSession:
    """Run one guarded demo session. `now` is injectable so the loop stays
    deterministic under test (no wall-clock in the hot path)."""
    is_demo = reader.is_demo()
    guard = SessionGuard(limits, is_demo=is_demo)  # refuses non-demo up front
    oracle = compile_spec(spec)
    started = now or datetime.now(UTC).isoformat()
    session = LiveSession(
        strategy=spec.name,
        spec_version=spec.version,
        table_url=table_url,
        is_demo=is_demo,
        started_at=started,
        limits=limits,
    )

    while True:
        action = oracle.next_action()
        if action.stop:
            session.stop_reason = action.reason or "strategy stop"
            break
        if not action.bets:
            # strategy sits this round out — still need a spin to advance history
            outcome = reader.read_next_spin()
            if outcome is None:
                session.stop_reason = "table unavailable"
                break
            oracle.observe(outcome)
            continue

        try:
            guard.check_bets(action.bets)
        except GuardViolation as exc:
            session.stop_reason = f"guard blocked bet: {exc}"
            break

        placer.place_bets(action.bets)
        outcome = reader.read_next_spin()
        if outcome is None:
            session.stop_reason = "table unavailable"
            break

        net = oracle.observe(outcome)
        session.net_units = oracle.net_units
        session.rounds.append(
            RecordedRound(
                round_index=oracle.rounds_played,
                outcome=_outcome_token(outcome),
                bets=[{"bet_type": b.bet_type, "stake_units": b.stake_units} for b in action.bets],
                net_units=net,
                cumulative_units=oracle.net_units,
            )
        )

        guard_stop = guard.check_session(oracle.net_units, oracle.rounds_played)
        if guard_stop:
            session.stop_reason = guard_stop
            break

    session.ended_at = now or datetime.now(UTC).isoformat()
    return session


def save_session(session: LiveSession, sessions_dir: Path = DEFAULT_SESSIONS_DIR) -> Path:
    """Persist a recorded live session; filename keys on start time + strategy."""
    sessions_dir.mkdir(parents=True, exist_ok=True)
    slug = session.strategy.lower().replace(" ", "-")
    stamp = session.started_at.replace(":", "").replace("-", "").replace(".", "")[:15]
    path = sessions_dir / f"live-{slug}-v{session.spec_version}-{stamp}.json"
    path.write_text(session.model_dump_json(indent=2))
    return path


def load_sessions(sessions_dir: Path = DEFAULT_SESSIONS_DIR) -> list[LiveSession]:
    if not sessions_dir.exists():
        return []
    return [
        LiveSession.model_validate_json(p.read_text()) for p in sorted(sessions_dir.glob("*.json"))
    ]
