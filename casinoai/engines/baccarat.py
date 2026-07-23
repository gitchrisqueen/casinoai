"""Seeded baccarat simulator (punto banco, 8-deck shoe, standard tableau).

Deterministic: seeded RNG only. Payouts: player 1:1, banker 1:1 less 5%
commission, tie 8:1; player/banker bets push on a tie.
"""

import random
from enum import StrEnum

from pydantic import BaseModel

# Card values: A=1, 2-9 pip, 10/J/Q/K=0. A deck as point values.
_DECK_VALUES = [1, 2, 3, 4, 5, 6, 7, 8, 9, 0, 0, 0, 0] * 4


class BaccaratWinner(StrEnum):
    PLAYER = "player"
    BANKER = "banker"
    TIE = "tie"


class BaccaratOutcome(BaseModel):
    winner: BaccaratWinner
    player_total: int
    banker_total: int
    player_cards: list[int]
    banker_cards: list[int]
    natural: bool


def _banker_draws(banker_total: int, player_third: int | None) -> bool:
    """Standard punto banco tableau for the banker's third card."""
    if player_third is None:  # player stood pat
        return banker_total <= 5
    if banker_total <= 2:
        return True
    if banker_total == 3:
        return player_third != 8
    if banker_total == 4:
        return 2 <= player_third <= 7
    if banker_total == 5:
        return 4 <= player_third <= 7
    if banker_total == 6:
        return player_third in (6, 7)
    return False


class BaccaratEngine:
    """Seeded 8-deck shoe; reshuffles behind the cut card. Same seed → same shoe order."""

    def __init__(self, seed: int = 0, decks: int = 8, cut_card: int = 14):
        self.seed = seed
        self.decks = decks
        self.cut_card = cut_card
        self._rng = random.Random(seed)
        self._shoe: list[int] = []
        self.round_index = 0

    def _reshuffle(self) -> None:
        self._shoe = _DECK_VALUES * self.decks
        self._rng.shuffle(self._shoe)

    def _draw(self) -> int:
        return self._shoe.pop()

    def deal(self) -> BaccaratOutcome:
        if len(self._shoe) <= self.cut_card:
            self._reshuffle()
        self.round_index += 1

        player = [self._draw(), self._draw()]
        banker = [self._draw(), self._draw()]
        p_total = sum(player) % 10
        b_total = sum(banker) % 10

        natural = p_total >= 8 or b_total >= 8
        if not natural:
            player_third: int | None = None
            if p_total <= 5:
                player_third = self._draw()
                player.append(player_third)
                p_total = sum(player) % 10
            if _banker_draws(b_total, player_third):
                banker.append(self._draw())
                b_total = sum(banker) % 10

        if p_total > b_total:
            winner = BaccaratWinner.PLAYER
        elif b_total > p_total:
            winner = BaccaratWinner.BANKER
        else:
            winner = BaccaratWinner.TIE
        return BaccaratOutcome(
            winner=winner,
            player_total=p_total,
            banker_total=b_total,
            player_cards=player,
            banker_cards=banker,
            natural=natural,
        )

    @staticmethod
    def settle(bet_type: str, stake: float, outcome: BaccaratOutcome) -> float:
        """Net result: banker pays 0.95:1, player 1:1, tie 8:1; player/banker push on tie."""
        if bet_type not in ("player", "banker", "tie"):
            raise ValueError(f"Unknown bet type: {bet_type}")
        if outcome.winner == BaccaratWinner.TIE:
            return stake * 8 if bet_type == "tie" else 0.0
        if bet_type == "tie":
            return -stake
        if bet_type == outcome.winner.value:
            return stake * 0.95 if bet_type == "banker" else stake * 1.0
        return -stake
