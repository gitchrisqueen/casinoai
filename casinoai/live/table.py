"""Table compatibility: does this strategy's stakes actually fit THIS table?

A strategy in units (Power Baccarat: 0.6, 1, 2, 3, 5, ...) becomes real currency
via the spec's base unit. Whether each of those amounts is *placeable* depends on
the live table's minimum bet, maximum bet, and chip denominations — a $3
Counterstrike bet can't be made on a $5-minimum table, and a $6 bet can't be made
if the smallest chip is $5. This module enumerates every stake a strategy can
require and checks each against a TableProfile, so we never assume a strategy
"works" on a table it can't actually be played on.
"""

from pydantic import BaseModel, Field

from casinoai.rules.library import PROGRESSIONS
from casinoai.strategies.spec import (
    FibonacciProgression,
    FlatProgression,
    LadderProgression,
    MultiplierProgression,
    RegisteredProgression,
    StrategySpec,
)

_TOL = 1e-6


class TableProfile(BaseModel):
    """A live/demo table's betting constraints."""

    name: str = "table"
    currency: str = "credits"
    min_bet: float
    max_bet: float
    chip_denominations: list[float] = Field(
        description="Available chip values, e.g. [1, 5, 25, 100, 500]"
    )


class TableCheck(BaseModel):
    ok: bool
    base_unit: float
    currency: str
    required_stakes: list[float]
    below_min: list[float]
    above_max: list[float]
    not_placeable: list[float]
    dynamic: bool  # stakes couldn't be fully enumerated (chip-stack machines)
    messages: list[str]


def strategy_unit_stakes(spec: StrategySpec) -> list[float]:
    """Every distinct stake (in UNITS) the strategy can require, best-effort.
    Empty when the progression's stakes are dynamic (e.g. Mini-Max chip stacks)."""
    p = spec.progression
    vals: set[float] = set()
    if isinstance(p, RegisteredProgression):
        machine = PROGRESSIONS.get(p.name)
        if machine is not None and hasattr(machine(), "schedule_view"):
            for v in machine().schedule_view().values():
                if isinstance(v, list):
                    vals.update(float(x) for x in v if isinstance(x, int | float))
    elif isinstance(p, LadderProgression):
        vals = {s.stake_units for s in p.steps}
    elif isinstance(p, FlatProgression):
        vals = {p.units}
    elif isinstance(p, MultiplierProgression):
        vals = {float(p.factor**i) for i in range(12)}
    elif isinstance(p, FibonacciProgression):
        fib = [1.0, 1.0]
        while len(fib) < 14:
            fib.append(fib[-1] + fib[-2])
        vals = set(fib[:14])
    cap = spec.bankroll.max_bet_units
    if cap is not None:
        vals = {min(v, cap) for v in vals}
    return sorted(vals)


def currency_stakes(spec: StrategySpec) -> list[float]:
    unit = spec.bankroll.unit_size or 1.0
    return sorted({round(u * unit, 2) for u in strategy_unit_stakes(spec)})


def _placeable(amount: float, chips: list[float]) -> bool:
    """Placeable if it's a whole multiple of the smallest chip (canonical chip
    sets like 1/5/25/100/500 are designed so this holds) and at least one chip."""
    if not chips:
        return True
    m = min(chips)
    q = amount / m
    return amount >= m - _TOL and abs(q - round(q)) < _TOL


def check_table(spec: StrategySpec, profile: TableProfile) -> TableCheck:
    unit = spec.bankroll.unit_size or 1.0
    stakes = currency_stakes(spec)
    dynamic = len(strategy_unit_stakes(spec)) == 0
    below = [s for s in stakes if s < profile.min_bet - _TOL]
    above = [s for s in stakes if s > profile.max_bet + _TOL]
    npl = [s for s in stakes if not _placeable(s, profile.chip_denominations)]
    msgs: list[str] = []
    if below:
        msgs.append(
            f"{len(below)} stake(s) below the table minimum {profile.min_bet:g}: "
            f"{', '.join(f'{s:g}' for s in below)} — the strategy can't place these."
        )
    if above:
        msgs.append(
            f"{len(above)} stake(s) above the table maximum {profile.max_bet:g}: "
            f"{', '.join(f'{s:g}' for s in above)}."
        )
    if npl:
        msgs.append(
            f"{len(npl)} stake(s) not placeable with chips "
            f"{[f'{c:g}' for c in profile.chip_denominations]}: "
            f"{', '.join(f'{s:g}' for s in npl)}."
        )
    if dynamic:
        msgs.append(
            f"Stakes are dynamic (chip-stack based) and couldn't be fully enumerated; "
            f"they are whole multiples of the base unit {unit:g} — confirm the table's "
            f"chips include it."
        )
    ok = not (below or above or npl)
    return TableCheck(
        ok=ok,
        base_unit=unit,
        currency=profile.currency,
        required_stakes=stakes,
        below_min=below,
        above_max=above,
        not_placeable=npl,
        dynamic=dynamic,
        messages=msgs,
    )


def render_check(spec: StrategySpec, profile: TableProfile, check: TableCheck) -> str:
    stakes = ", ".join(f"{s:g}" for s in check.required_stakes) or "(dynamic)"
    lines = [
        f"Table compatibility — {spec.name} on '{profile.name}'",
        f"  base unit: {check.base_unit:g} {profile.currency}",
        f"  table: min {profile.min_bet:g}, max {profile.max_bet:g}, "
        f"chips {[f'{c:g}' for c in profile.chip_denominations]}",
        f"  strategy needs stakes: {stakes}",
    ]
    if check.ok and not check.dynamic:
        lines.append("  ✓ all required stakes are placeable on this table")
    else:
        for m in check.messages:
            lines.append(f"  ⚠ {m}")
        if check.below_min or check.above_max or check.not_placeable:
            lines.append(
                "  → fix by choosing a different base unit (bankroll.unit_size) or a "
                "table whose min/chips cover these stakes."
            )
    return "\n".join(lines)
