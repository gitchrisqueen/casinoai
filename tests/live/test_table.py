"""Table-compatibility checks: do a strategy's stakes fit the table?"""

from casinoai.live.table import (
    TableProfile,
    check_table,
    currency_stakes,
    strategy_unit_stakes,
)
from casinoai.strategies import load_spec


def test_power_baccarat_currency_stakes():
    spec = load_spec("strategies/approved/power-baccarat-v2.yaml")
    stakes = currency_stakes(spec)  # $5 base
    # Counterstrike level 1 is 0.6 units -> $3; Strike level 1 -> $5
    assert 3.0 in stakes
    assert 5.0 in stakes
    assert 170.0 in stakes  # Strike level 8 (34u * $5)


def test_power_baccarat_flagged_on_five_dollar_minimum_table():
    """The real case: a $5-minimum table can't place the $3 Counterstrike bet."""
    spec = load_spec("strategies/approved/power-baccarat-v2.yaml")
    table = TableProfile(min_bet=5.0, max_bet=1000.0, chip_denominations=[5, 25, 100, 500])
    check = check_table(spec, table)
    assert not check.ok
    assert 3.0 in check.below_min  # $3 below the $5 minimum
    assert 3.0 in check.not_placeable  # and not composable from $5+ chips


def test_power_baccarat_ok_on_one_dollar_table_with_ones():
    """The captured OneTouch table: min 1, chips include 1 -> everything places."""
    spec = load_spec("strategies/approved/power-baccarat-v2.yaml")
    table = TableProfile(min_bet=1.0, max_bet=1000.0, chip_denominations=[1, 5, 25, 100, 500])
    check = check_table(spec, table)
    assert check.ok
    assert check.below_min == [] and check.not_placeable == []


def test_max_bet_exceeded_is_flagged():
    spec = load_spec("strategies/approved/power-baccarat-v2.yaml")
    table = TableProfile(min_bet=1.0, max_bet=50.0, chip_denominations=[1, 5, 25])
    check = check_table(spec, table)
    assert not check.ok
    assert any(s > 50 for s in check.above_max)


def test_mini_max_is_dynamic():
    """Mini-Max stakes are chip-stack based; enumeration is empty -> flagged
    dynamic so the operator verifies manually."""
    spec = load_spec("strategies/approved/mini-max-roulette-v2.yaml")
    assert strategy_unit_stakes(spec) == []
    table = TableProfile(min_bet=1.0, max_bet=1000.0, chip_denominations=[1, 5, 25])
    check = check_table(spec, table)
    assert check.dynamic


def test_operator_verify_table_flow(capsys):
    from casinoai.live.operator import verify_table

    spec = load_spec("strategies/approved/power-baccarat-v2.yaml")
    # $5-min table, no $1 chips: verify_table should flag it and, on "n", abort
    answers = iter(["5,25,100,500", "5", "1000", "n"])
    aborted = verify_table(spec, read_fn=lambda _p: next(answers))
    out = capsys.readouterr().out
    assert "below the table minimum" in out
    assert aborted is None  # None == abort

    # $1 table with $1 chips: passes and returns the confirmed profile (chips reused)
    answers2 = iter(["1,5,25,100,500", "1", "1000"])
    profile = verify_table(spec, read_fn=lambda _p: next(answers2))
    assert profile is not None
    assert profile.chip_denominations == [1, 5, 25, 100, 500]


def test_operator_bet_placer_prints_currency_and_chips():
    """A 1.2u bet on a $5-unit table is shown as its real amount ($6) and the
    exact chip stack, so the instruction matches the verified stakes — not '1.2u'
    read as an unplaceable $1.20."""
    from types import SimpleNamespace

    from casinoai.live.playwright_adapter import OperatorBetPlacer

    lines: list[str] = []
    placer = OperatorBetPlacer(printer=lines.append, unit_size=5.0, chips=[1, 5, 25, 100, 500])
    placer.place_bets([SimpleNamespace(stake_units=1.2, bet_type="player")])
    assert "6 credits" in lines[0]
    assert "1.2u" in lines[0]
    assert "chips 5+1" in lines[0]

    # Raw-units fallback when the table isn't known.
    plain: list[str] = []
    OperatorBetPlacer(printer=plain.append).place_bets(
        [SimpleNamespace(stake_units=1.2, bet_type="player")]
    )
    assert plain[0] == "[OPERATOR] Place: 1.2u on player"
