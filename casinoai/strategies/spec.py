"""StrategySpec — the machine-executable form of a betting strategy.

Extraction fills this from a parsed PDF; the rule engine (Phase 3) compiles
it into a deterministic oracle. Anything the source leaves unclear goes in
`ambiguities` for human review — extraction must never silently guess.
"""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class GameType(StrEnum):
    ROULETTE = "roulette"
    BLACKJACK = "blackjack"
    CRAPS = "craps"
    BACCARAT = "baccarat"


class TableRules(BaseModel):
    """Table assumptions the strategy depends on (wheel type, limits, etc.)."""

    variant: str | None = Field(
        default=None, description="e.g. 'european' or 'american' roulette, '6-deck S17' blackjack"
    )
    min_bet: float | None = None
    max_bet: float | None = None
    notes: list[str] = Field(default_factory=list)


class BetSpec(BaseModel):
    """One bet the strategy places."""

    bet_type: str = Field(
        description="Canonical bet name, e.g. red, black, even, odd, dozen_1, straight_17, "
        "pass_line, banker, player"
    )
    description: str | None = None


# --- Betting progressions (discriminated union) ---------------------------------


class FlatProgression(BaseModel):
    kind: Literal["flat"] = "flat"
    units: float = 1.0


class MultiplierProgression(BaseModel):
    """Martingale-style: multiply the stake on win or loss, reset on the other."""

    kind: Literal["multiplier"] = "multiplier"
    factor: float = 2.0
    on: Literal["loss", "win"] = "loss"
    reset_after_steps: int | None = Field(
        default=None, description="Cap on progression length; None = uncapped"
    )


class FibonacciProgression(BaseModel):
    kind: Literal["fibonacci"] = "fibonacci"
    on: Literal["loss", "win"] = "loss"
    step_back_on_win: int = Field(
        default=2, description="How many sequence positions to step back after a win"
    )


class LadderStep(BaseModel):
    stake_units: float
    note: str | None = None


class LadderProgression(BaseModel):
    """Explicit stake table: advance/retreat through fixed steps."""

    kind: Literal["ladder"] = "ladder"
    steps: list[LadderStep]
    advance_on: Literal["loss", "win"] = "loss"
    retreat_steps: int = Field(default=1, description="Steps back on the opposite outcome")
    reset_at_end: bool = True


class CustomProgression(BaseModel):
    """A progression the schema cannot express (procedural chip-stack rules,
    mode switches, etc.). Never compilable — a human must translate it."""

    kind: Literal["custom"] = "custom"
    description: str
    rules: list[str] = Field(
        default_factory=list, description="The source's progression rules, verbatim-ish"
    )


Progression = Annotated[
    FlatProgression
    | MultiplierProgression
    | FibonacciProgression
    | LadderProgression
    | CustomProgression,
    Field(discriminator="kind"),
]


# --- Entry / exit conditions ----------------------------------------------------


class StreakCondition(BaseModel):
    """e.g. 'after 3 consecutive reds, bet black'."""

    kind: Literal["streak"] = "streak"
    outcome: str = Field(description="Outcome being counted, e.g. red, banker, pass")
    count: int


class AlwaysCondition(BaseModel):
    kind: Literal["always"] = "always"


class CustomCondition(BaseModel):
    """A condition the schema cannot yet express — must be reviewed by a human."""

    kind: Literal["custom"] = "custom"
    description: str


Condition = Annotated[
    StreakCondition | AlwaysCondition | CustomCondition,
    Field(discriminator="kind"),
]


class BankrollRules(BaseModel):
    unit_size: float | None = Field(default=None, description="Base bet in currency units")
    session_bankroll_units: float | None = None
    stop_loss_units: float | None = None
    stop_win_units: float | None = None
    max_bet_units: float | None = None


class SourceRef(BaseModel):
    """Ties a spec back to the exact parsed document it came from."""

    pdf_path: str
    sha256: str
    parser: str


class ApprovalRecord(BaseModel):
    """Set only by the human review gate — never by extraction."""

    approved_by: str
    approved_at: str
    annotations: list[str] = Field(
        default_factory=list, description="Reviewer resolutions of ambiguities, clarifications"
    )


class StrategySpec(BaseModel):
    name: str
    version: int = 1
    game: GameType = Field(description="Primary game — the one the source describes in most detail")
    also_applicable_to: list[GameType] = Field(
        default_factory=list,
        description="Other games the source says the same system applies to",
    )
    summary: str = Field(description="2-4 sentence plain-English summary of the strategy")
    table_rules: TableRules = Field(default_factory=TableRules)
    bets: list[BetSpec]
    entry_conditions: list[Condition] = Field(
        default_factory=list, description="When to start/place bets; empty means bet every round"
    )
    progression: Progression
    bankroll: BankrollRules = Field(default_factory=BankrollRules)
    state_tracked: list[str] = Field(
        default_factory=list, description="e.g. 'consecutive reds', 'shoe count', 'session P/L'"
    )
    assumptions: list[str] = Field(
        default_factory=list, description="Things the source implies but never states"
    )
    ambiguities: list[str] = Field(
        default_factory=list,
        description="Things the source leaves unclear — NEVER guess; record here for human review",
    )
    source: SourceRef | None = None
    approval: ApprovalRecord | None = None


class ExtractionResult(BaseModel):
    """What the extraction LLM returns (spec without provenance, added after)."""

    spec: StrategySpec
    extraction_notes: list[str] = Field(
        default_factory=list, description="Extractor's remarks on difficulty or document quality"
    )
