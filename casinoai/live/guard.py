"""Hard safety limits for live/demo play — enforced in code, un-overridable.

These caps are independent of (and stricter than) anything in a StrategySpec.
A spec's own stop-loss can be large; the guard is a second, absolute backstop.
Per project ground rules: live play is demo/free-play only, human-initiated,
with hard bet/session limits enforced here. The guard NEVER permits real-money
play and never bypasses site protections — it only stops early, never presses on.
"""

from pydantic import BaseModel, Field


class GuardViolation(Exception):
    """A hard limit was hit; the session must stop immediately."""


class SessionLimits(BaseModel):
    """Absolute caps for one live/demo session. All in base units."""

    demo_only: bool = Field(default=True, description="Must stay True; real-money play is refused")
    max_bet_units: float = Field(default=8.0, description="Cap on any single bet")
    max_total_stake_units: float = Field(default=16.0, description="Cap on total staked per round")
    max_rounds: int = Field(default=200, description="Hard session length cap")
    stop_loss_units: float = Field(default=40.0, description="Hard session loss cap (absolute)")
    stop_win_units: float | None = Field(default=None, description="Optional session win cap")


class SessionGuard:
    """Checks each round against the limits; raises GuardViolation on breach."""

    def __init__(self, limits: SessionLimits, is_demo: bool):
        if limits.demo_only and not is_demo:
            raise GuardViolation(
                "Refusing to run: demo_only is set but the table is not in demo/free-play mode"
            )
        self.limits = limits
        self.is_demo = is_demo

    def check_bets(self, bets: list) -> None:
        """Pre-placement: no bet or round total may exceed the caps."""
        total = 0.0
        for bet in bets:
            if bet.stake_units > self.limits.max_bet_units:
                raise GuardViolation(
                    f"bet {bet.stake_units}u exceeds max_bet {self.limits.max_bet_units}u"
                )
            total += bet.stake_units
        if total > self.limits.max_total_stake_units:
            raise GuardViolation(
                f"round stake {total}u exceeds max_total_stake {self.limits.max_total_stake_units}u"
            )

    def check_session(self, net_units: float, rounds_played: int) -> str | None:
        """Post-round: returns a stop reason if a session cap is reached, else None.
        Loss/round caps are hard stops; hitting one is normal, not an error."""
        if net_units <= -self.limits.stop_loss_units:
            return f"guard stop-loss ({net_units:+.1f}u)"
        if self.limits.stop_win_units is not None and net_units >= self.limits.stop_win_units:
            return f"guard stop-win ({net_units:+.1f}u)"
        if rounds_played >= self.limits.max_rounds:
            return f"guard max-rounds ({rounds_played})"
        return None
