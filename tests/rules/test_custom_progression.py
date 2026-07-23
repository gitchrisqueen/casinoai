"""Custom progressions must never reach the oracle without human translation."""

import pytest

from casinoai.rules.oracle import CompileError, compile_spec
from tests.rules.test_oracle import martingale_spec


def test_custom_progression_refuses_to_compile():
    spec = martingale_spec(
        progression={
            "kind": "custom",
            "description": "Three chip stacks with redistribution rules",
            "rules": ["Bet A first", "Refill B then C then A on wins"],
        }
    )
    with pytest.raises(CompileError, match="custom progression"):
        compile_spec(spec)
