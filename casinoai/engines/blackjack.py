"""Seeded blackjack simulator: 6-deck shoe, dealer stands on soft 17,
blackjack pays 3:2, double any two cards, DAS, split to two hands
(split aces get one card), no surrender, no insurance, American peek.

The engine plays the player's hand with fixed basic strategy — CasinoAI's
blackjack systems are bet-sizing systems layered on basic strategy, so play
decisions are deterministic engine behavior, not strategy behavior. Outcomes
report a net multiplier per base unit staked (doubles/splits scale it).
"""

import random

from pydantic import BaseModel

# ranks: 2-9 pip, 10 for T/J/Q/K, 11 for ace
_DECK = [2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 10, 10, 11] * 4


def hand_value(cards: list[int]) -> tuple[int, bool]:
    """(best total, is_soft) — aces drop from 11 to 1 as needed."""
    total = sum(cards)
    aces = cards.count(11)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total, aces > 0


class BlackjackOutcome(BaseModel):
    net_multiplier: float  # net result per base unit staked
    total_staked_multiplier: float  # 1.0, 2.0 (double), up to 4.0 (split+doubles)
    player_totals: list[int]
    dealer_total: int
    player_blackjack: bool
    dealer_blackjack: bool
    doubled: bool
    split: bool


def _basic_strategy(cards: list[int], dealer_up: int, can_double: bool, can_split: bool) -> str:
    """6-deck S17 DAS basic strategy: returns hit/stand/double/split."""
    total, soft = hand_value(cards)
    if can_split and len(cards) == 2 and cards[0] == cards[1]:
        pair = cards[0]
        if pair == 11 or pair == 8:
            return "split"
        if pair == 9 and dealer_up in (2, 3, 4, 5, 6, 8, 9):
            return "split"
        if pair == 7 and dealer_up <= 7:
            return "split"
        if pair == 6 and dealer_up <= 6:
            return "split"
        if pair == 4 and dealer_up in (5, 6):
            return "split"
        if pair in (2, 3) and dealer_up <= 7:
            return "split"
        # 10,10 and 5,5 fall through to totals
    if soft:
        if total >= 19:
            return "stand"
        if total == 18:
            if dealer_up <= 6:
                return "double" if can_double else "stand"
            return "stand" if dealer_up in (7, 8) else "hit"
        if total == 17 and 3 <= dealer_up <= 6:
            return "double" if can_double else "hit"
        if total in (15, 16) and 4 <= dealer_up <= 6:
            return "double" if can_double else "hit"
        if total in (13, 14) and 5 <= dealer_up <= 6:
            return "double" if can_double else "hit"
        return "hit"
    if total >= 17:
        return "stand"
    if 13 <= total <= 16:
        return "stand" if dealer_up <= 6 else "hit"
    if total == 12:
        return "stand" if 4 <= dealer_up <= 6 else "hit"
    if total == 11:
        if dealer_up == 11:
            return "hit"
        return "double" if can_double else "hit"
    if total == 10:
        if dealer_up <= 9:
            return "double" if can_double else "hit"
        return "hit"
    if total == 9 and 3 <= dealer_up <= 6:
        return "double" if can_double else "hit"
    return "hit"


class BlackjackEngine:
    """Seeded 6-deck shoe; reshuffles behind the cut card."""

    def __init__(self, seed: int = 0, decks: int = 6, cut_card: int = 52):
        self.seed = seed
        self.decks = decks
        self.cut_card = cut_card
        self._rng = random.Random(seed)
        self._shoe: list[int] = []
        self.round_index = 0

    def _draw(self) -> int:
        return self._shoe.pop()

    def deal(self) -> BlackjackOutcome:
        if len(self._shoe) <= self.cut_card:
            self._shoe = _DECK * self.decks
            self._rng.shuffle(self._shoe)
        self.round_index += 1

        player = [self._draw(), self._draw()]
        dealer = [self._draw(), self._draw()]
        dealer_up = dealer[0]
        player_bj = hand_value(player)[0] == 21
        dealer_bj = hand_value(dealer)[0] == 21

        if dealer_bj or player_bj:  # peek resolves naturals immediately
            if player_bj and dealer_bj:
                net = 0.0
            elif player_bj:
                net = 1.5
            else:
                net = -1.0
            return BlackjackOutcome(
                net_multiplier=net,
                total_staked_multiplier=1.0,
                player_totals=[hand_value(player)[0]],
                dealer_total=hand_value(dealer)[0],
                player_blackjack=player_bj,
                dealer_blackjack=dealer_bj,
                doubled=False,
                split=False,
            )

        # play out player hand(s) with basic strategy
        hands: list[tuple[list[int], float]] = []  # (cards, stake multiplier)
        doubled = split = False
        queue: list[tuple[list[int], bool]] = [(player, False)]  # (cards, from_split_aces)
        allow_split = True
        while queue:
            cards, aces_split = queue.pop(0)
            if aces_split:
                cards.append(self._draw())  # split aces: one card, then stand
                hands.append((cards, 1.0))
                continue
            stake = 1.0
            while True:
                action = _basic_strategy(
                    cards, dealer_up, can_double=len(cards) == 2, can_split=allow_split
                )
                if action == "split" and allow_split:
                    allow_split = False  # split once (two hands max)
                    split = True
                    is_aces = cards[0] == 11
                    queue.append(([cards[0], self._draw()], is_aces))
                    queue.append(([cards[1], self._draw()], is_aces))
                    cards = []
                    break
                if action == "double":
                    stake = 2.0
                    doubled = True
                    cards.append(self._draw())
                    break
                if action == "hit":
                    cards.append(self._draw())
                    if hand_value(cards)[0] > 21:
                        break
                    continue
                break  # stand
            if cards:
                hands.append((cards, stake))

        # dealer plays only if any player hand is live
        any_live = any(hand_value(c)[0] <= 21 for c, _ in hands)
        if any_live:
            while hand_value(dealer)[0] < 17:  # S17: stand on all 17s
                dealer.append(self._draw())
        dealer_total = hand_value(dealer)[0]

        net = 0.0
        total_staked = 0.0
        totals = []
        for cards, stake in hands:
            total, _ = hand_value(cards)
            totals.append(total)
            total_staked += stake
            if total > 21:
                net -= stake
            elif dealer_total > 21 or total > dealer_total:
                net += stake
            elif total < dealer_total:
                net -= stake
        return BlackjackOutcome(
            net_multiplier=net,
            total_staked_multiplier=total_staked,
            player_totals=totals,
            dealer_total=dealer_total,
            player_blackjack=False,
            dealer_blackjack=False,
            doubled=doubled,
            split=split,
        )

    @staticmethod
    def settle(bet_type: str, stake: float, outcome: BlackjackOutcome) -> float:
        """One 'hand' bet: stake is the base unit; doubles/splits scale it."""
        if bet_type != "hand":
            raise ValueError(f"Unknown bet type: {bet_type}")
        return stake * outcome.net_multiplier
