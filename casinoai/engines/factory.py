"""Engine factory: spec → seeded game engine, shared by backtest and harness."""

from casinoai.engines.baccarat import BaccaratEngine
from casinoai.engines.blackjack import BlackjackEngine
from casinoai.engines.roulette import RouletteEngine, Wheel
from casinoai.strategies.spec import GameType, StrategySpec


def make_engine(spec: StrategySpec, seed: int):
    if spec.game == GameType.ROULETTE:
        variant = (spec.table_rules.variant or "european").lower()
        wheel = Wheel.AMERICAN if "american" in variant else Wheel.EUROPEAN
        return RouletteEngine(wheel=wheel, seed=seed)
    if spec.game == GameType.BACCARAT:
        return BaccaratEngine(seed=seed)
    if spec.game == GameType.BLACKJACK:
        return BlackjackEngine(seed=seed)
    raise ValueError(f"No engine for game {spec.game}")


def play_round(engine):
    """Advance the engine one round and return its typed outcome."""
    return engine.spin() if isinstance(engine, RouletteEngine) else engine.deal()
