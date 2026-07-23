"""Strategy identity: fingerprints, similarity, and the dedup registry."""

from casinoai.strategies.identity import (
    StrategyRegistry,
    core_fingerprint,
    full_fingerprint,
    similarity,
)
from casinoai.strategies.spec import StrategySpec


def martingale(name, bet="red", factor=2.0, unit=1.0, stop_loss=63.0):
    return StrategySpec.model_validate(
        {
            "name": name,
            "game": "roulette",
            "summary": "double on loss",
            "table_rules": {"variant": "european"},
            "bets": [{"bet_type": bet}],
            "progression": {"kind": "multiplier", "factor": factor, "on": "loss"},
            "bankroll": {"unit_size": unit, "stop_loss_units": stop_loss},
        }
    )


def test_same_system_different_name_and_unit_matches():
    a = martingale("Martingale", bet="red", unit=1.0)
    b = martingale("The Double-Up System", bet="black", unit=10.0)  # renamed, $10, black
    # red vs black are the same even-money class; unit size ignored
    assert core_fingerprint(a) == core_fingerprint(b)


def test_different_factor_is_a_different_system():
    assert core_fingerprint(martingale("M2", factor=2.0)) != core_fingerprint(
        martingale("M3", factor=3.0)
    )


def test_stop_settings_split_full_but_not_core():
    a = martingale("M", stop_loss=63.0)
    b = martingale("M", stop_loss=1000.0)
    assert core_fingerprint(a) == core_fingerprint(b)  # same system
    assert full_fingerprint(a) != full_fingerprint(b)  # different exact config


def test_registry_exact_same_system_and_new():
    reg = StrategyRegistry()
    reg.register(martingale("Martingale", stop_loss=63.0), "book:martingale")

    exact = reg.check(martingale("Double-Up", bet="black", stop_loss=63.0))
    assert exact.status == "exact_duplicate"
    assert exact.matched_name == "Martingale"

    variant = reg.check(martingale("Martingale XL", stop_loss=255.0))
    assert variant.status == "same_system"

    fresh = reg.check(martingale("Triple Threat", factor=3.0))
    assert fresh.status == "new"


def test_near_duplicate_flag():
    reg = StrategyRegistry(near_threshold=0.85)
    known = martingale("Martingale", factor=2.0)
    reg.register(known, "book:martingale")
    # same game, same progression KIND, different factor -> similar but not equal
    candidate = martingale("Almost Martingale", factor=2.5)
    result = reg.check(candidate, known_specs=[known])
    assert 0.0 < result.similarity < 1.0
    # progression kind + selection + bet class + game match => >= 0.85
    assert result.status == "near_duplicate"


def test_baccarat_player_and_banker_are_distinct():
    def bacc(bet):
        return StrategySpec.model_validate(
            {
                "name": bet,
                "game": "baccarat",
                "summary": "x",
                "bets": [{"bet_type": bet}],
                "progression": {"kind": "flat", "units": 1.0},
            }
        )

    # different edge classes -> not the same system
    assert core_fingerprint(bacc("player")) != core_fingerprint(bacc("banker"))
    assert similarity(bacc("player"), bacc("banker")) < 1.0


def test_registry_save_load(tmp_path):
    reg = StrategyRegistry()
    reg.register(martingale("Martingale"), "book:martingale")
    path = reg.save(tmp_path / "registry.json")
    reloaded = StrategyRegistry.load(path)
    assert reg.check(martingale("Double-Up", bet="black")).status == "exact_duplicate"
    assert reloaded.check(martingale("Double-Up", bet="black")).status == "exact_duplicate"
