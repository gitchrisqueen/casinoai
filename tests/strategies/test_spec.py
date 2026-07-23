"""StrategySpec schema tests: discriminated unions and YAML round-trip."""

import pytest
from pydantic import ValidationError

from casinoai.strategies import StrategySpec, load_spec, save_spec


def sample_spec() -> StrategySpec:
    return StrategySpec.model_validate(
        {
            "name": "Test Ladder",
            "game": "roulette",
            "summary": "Bet red, climb a ladder on losses.",
            "bets": [{"bet_type": "red"}],
            "entry_conditions": [{"kind": "streak", "outcome": "black", "count": 3}],
            "progression": {
                "kind": "ladder",
                "steps": [{"stake_units": 1}, {"stake_units": 2}, {"stake_units": 4}],
                "advance_on": "loss",
            },
            "bankroll": {"unit_size": 5, "stop_loss_units": 40},
            "ambiguities": ["Source never says what to do at the top of the ladder"],
        }
    )


def test_discriminated_unions_parse():
    spec = sample_spec()
    assert spec.progression.kind == "ladder"
    assert spec.progression.steps[2].stake_units == 4
    assert spec.entry_conditions[0].count == 3


def test_unknown_progression_kind_rejected():
    bad = sample_spec().model_dump(mode="json")
    bad["progression"] = {"kind": "psychic"}
    with pytest.raises(ValidationError):
        StrategySpec.model_validate(bad)


def test_yaml_round_trip(tmp_path):
    spec = sample_spec()
    path = save_spec(spec, spec_dir=tmp_path)
    assert path.name == "test-ladder.yaml"
    assert load_spec(path) == spec
