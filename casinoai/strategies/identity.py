"""Strategy identity: fingerprint a StrategySpec by what it *does*, so we don't
reprocess the same system under a different name.

Two fingerprints:
- core_fingerprint: game + bet payout-class + selection + progression SHAPE
  (unit-independent — a $5 and a $10 Martingale match). This is the system's
  identity; "Martingale", "Double-Up", "Guaranteed Red" all collapse to one.
- full_fingerprint: core + the bankroll stop rules, for exact backtest-equivalence.

A StrategyRegistry answers new / exact_duplicate / same_system / near_duplicate
before we spend a backtest on something we already know.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from casinoai.strategies.spec import GameType, StrategySpec

DEFAULT_REGISTRY = Path("data/registry/registry.json")

# Bet → payout-equivalence class per game. Mechanically identical bets (e.g. red
# vs black, dozen_1 vs dozen_2 on a symmetric wheel) share a class.
_ROULETTE_EVEN = {"red", "black", "even", "odd", "low", "high", "even_money"}


def bet_class(game: GameType, bet_type: str) -> str:
    if game == GameType.ROULETTE:
        if bet_type in _ROULETTE_EVEN:
            return "roulette:even_money"
        if bet_type.startswith("dozen_") or bet_type.startswith("column_"):
            return "roulette:2to1"
        if bet_type.startswith("straight_") or bet_type == "zero":
            return "roulette:straight"
        return f"roulette:{bet_type}"
    # baccarat player/banker/tie, craps pass/dont_pass, blackjack hand — distinct
    return f"{game.value}:{bet_type}"


def _progression_shape(spec: StrategySpec) -> list:
    """Unit-independent shape of the progression (magnitudes normalized away)."""
    p = spec.progression
    kind = p.kind
    if kind == "flat":
        return ["flat"]
    if kind == "multiplier":
        return ["multiplier", round(p.factor, 4), p.on, p.reset_after_steps]
    if kind == "fibonacci":
        return ["fibonacci", p.on, p.step_back_on_win]
    if kind == "ladder":
        steps = [s.stake_units for s in p.steps]
        base = steps[0] if steps and steps[0] else 1.0
        ratios = [round(s / base, 4) for s in steps]  # normalize by first step
        wrm = [[r.from_step, r.to_step, r.go_to] for r in (p.win_retreat_map or [])]
        return ["ladder", ratios, p.advance_on, p.retreat_steps, wrm, p.reset_at_end, p.bust_at_end]
    if kind == "registered":
        return ["registered", p.name]
    if kind == "custom":
        return ["custom", hashlib.sha256(p.description.encode()).hexdigest()[:12]]
    return [kind]


def _selection_shape(spec: StrategySpec) -> list:
    s = spec.bet_selection
    if s.kind == "follow_lag":
        return ["follow_lag", s.attribute, s.lag]
    if s.kind in ("registered", "custom"):
        return [s.kind, getattr(s, "name", None) or getattr(s, "description", "")[:12]]
    return [s.kind]


def _features(spec: StrategySpec, granular: bool) -> dict:
    """Behavior features. granular=True keeps the SPECIFIC bet target (so red,
    black, dozen_1 are distinct strategies — they can diverge on a real/biased
    wheel); granular=False collapses to the payout CLASS (the shared mechanic)."""
    if granular:
        bets = sorted(b.bet_type for b in spec.bets)
    else:
        bets = sorted({bet_class(spec.game, b.bet_type) for b in spec.bets})
    return {
        "game": spec.game.value,
        "bets": bets,
        "selection": _selection_shape(spec),
        "progression": _progression_shape(spec),
    }


def _hash(obj) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()[:16]


def core_fingerprint(spec: StrategySpec) -> str:
    """Strategy identity, INCLUDING the specific board target — ignores unit
    size, name, and bankroll stops. red vs black vs dozen_1 are distinct."""
    return _hash(_features(spec, granular=True))


def mechanic_fingerprint(spec: StrategySpec) -> str:
    """The shared MECHANIC (payout-class level) — Martingale-on-even-money
    regardless of red vs black. Used to surface 'same mechanic, different board
    position' as a near-duplicate rather than collapsing it."""
    return _hash(_features(spec, granular=False))


def full_fingerprint(spec: StrategySpec) -> str:
    """Core + behavior-changing bankroll stops (in units, so unit-independent)."""
    bk = spec.bankroll
    stops = {
        "stop_loss_units": bk.stop_loss_units,
        "stop_win_units": bk.stop_win_units,
        "max_bet_units": bk.max_bet_units,
        "max_rounds": bk.max_rounds,
        "session_bankroll_units": bk.session_bankroll_units,
    }
    return _hash({"core": _features(spec, granular=True), "stops": stops})


def similarity(a: StrategySpec, b: StrategySpec) -> float:
    """Structural similarity in [0,1] at the MECHANIC (payout-class) level, so
    same-mechanic-different-board-position scores high. Different games = 0."""
    if a.game != b.game:
        return 0.0
    fa, fb = _features(a, granular=False), _features(b, granular=False)
    score = 0.0
    # progression kind (0.35) + full progression shape (0.15)
    pa, pb = fa["progression"], fb["progression"]
    if pa[0] == pb[0]:
        score += 0.35
        if pa == pb:
            score += 0.15
    # selection (0.2)
    if fa["selection"] == fb["selection"]:
        score += 0.20
    # bet classes (0.15, Jaccard)
    sa, sb = set(fa["bets"]), set(fb["bets"])
    if sa or sb:
        score += 0.15 * len(sa & sb) / len(sa | sb)
    # game already equal (0.15)
    score += 0.15
    return round(score, 4)


def load_approved_specs(approved_dir: Path = Path("strategies/approved")) -> list[StrategySpec]:
    from casinoai.strategies import load_spec

    if not approved_dir.exists():
        return []
    return [load_spec(p) for p in sorted(approved_dir.glob("*.yaml"))]


class RegistryEntry(BaseModel):
    core_fingerprint: str
    mechanic_fingerprint: str = ""
    full_fingerprints: list[str] = Field(default_factory=list)
    canonical_name: str
    game: str
    sources: list[str] = Field(default_factory=list)  # spec paths / source URLs
    first_seen: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class MatchResult(BaseModel):
    status: Literal["new", "exact_duplicate", "same_system", "near_duplicate"]
    core_fingerprint: str
    matched_name: str | None = None
    similarity: float = 1.0
    reason: str = ""


class StrategyRegistry:
    """Persistent registry of processed strategies, keyed by core fingerprint."""

    def __init__(self, entries: list[RegistryEntry] | None = None, near_threshold: float = 0.85):
        self.entries: dict[str, RegistryEntry] = {e.core_fingerprint: e for e in (entries or [])}
        self.near_threshold = near_threshold

    @classmethod
    def load(
        cls, path: Path = DEFAULT_REGISTRY, near_threshold: float = 0.85
    ) -> "StrategyRegistry":
        if not Path(path).exists():
            return cls(near_threshold=near_threshold)
        data = json.loads(Path(path).read_text())
        return cls([RegistryEntry.model_validate(e) for e in data], near_threshold)

    def save(self, path: Path = DEFAULT_REGISTRY) -> Path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps([e.model_dump() for e in self.entries.values()], indent=2))
        return Path(path)

    def check(
        self, spec: StrategySpec, known_specs: list[StrategySpec] | None = None
    ) -> MatchResult:
        """Classify a spec against what we've already processed (no side effects):
        exact_duplicate / same_system (by fingerprint), then near_duplicate if
        `known_specs` are supplied to compute structural similarity, else new."""
        core = core_fingerprint(spec)
        full = full_fingerprint(spec)
        mech = mechanic_fingerprint(spec)
        if core in self.entries:
            entry = self.entries[core]
            if full in entry.full_fingerprints:
                return MatchResult(
                    status="exact_duplicate",
                    core_fingerprint=core,
                    matched_name=entry.canonical_name,
                    reason="identical strategy (same board target, mechanics, and stops)",
                )
            return MatchResult(
                status="same_system",
                core_fingerprint=core,
                matched_name=entry.canonical_name,
                reason="same strategy, different bankroll/stop settings",
            )
        # same mechanic on a DIFFERENT board position (e.g. Martingale on black
        # when we already have it on red): surfaced for review, never auto-dropped
        for entry in self.entries.values():
            if entry.mechanic_fingerprint and entry.mechanic_fingerprint == mech:
                return MatchResult(
                    status="near_duplicate",
                    core_fingerprint=core,
                    matched_name=entry.canonical_name,
                    similarity=0.9,
                    reason="same mechanic as an existing system on a different board "
                    "position/target — may diverge on a real wheel; review",
                )
        best_name, best_sim = None, 0.0
        for other in known_specs or []:
            if other.game != spec.game or core_fingerprint(other) == core:
                continue
            sim = similarity(spec, other)
            if sim > best_sim:
                best_sim, best_name = sim, other.name
        if best_name and best_sim >= self.near_threshold:
            return MatchResult(
                status="near_duplicate",
                core_fingerprint=core,
                matched_name=best_name,
                similarity=best_sim,
                reason=f"structurally similar ({best_sim:.0%})",
            )
        return MatchResult(status="new", core_fingerprint=core, similarity=best_sim)

    def register(self, spec: StrategySpec, source: str) -> RegistryEntry:
        """Add or update the entry for this spec; returns the entry."""
        core = core_fingerprint(spec)
        full = full_fingerprint(spec)
        entry = self.entries.get(core)
        if entry is None:
            entry = RegistryEntry(
                core_fingerprint=core,
                mechanic_fingerprint=mechanic_fingerprint(spec),
                canonical_name=spec.name,
                game=spec.game.value,
            )
            self.entries[core] = entry
        if full not in entry.full_fingerprints:
            entry.full_fingerprints.append(full)
        if source not in entry.sources:
            entry.sources.append(source)
        return entry
