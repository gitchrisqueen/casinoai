"""Phase 8 — strategy discovery from online research.

The heart of Phase 8 is the *claims ledger*: for each strategy found online, we
record what its promoter claims (win rate, $/hour, "guaranteed", …) and, after
running it through the standard pipeline (extract → review → backtest), what we
actually measured. The deliverable is a growing, reproducible scoreboard of
hyped claims vs. reality.
"""

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

DEFAULT_CLAIMS_DIR = Path("data/claims")


class ClaimedMetrics(BaseModel):
    """What a strategy's promoter claims — the marketing numbers to test."""

    win_rate: float | None = Field(default=None, description="Claimed win rate (0-1)")
    dollars_per_hour: float | None = None
    dollars_per_day: float | None = None
    beats_house_edge: bool | None = Field(
        default=None, description="Claims positive expectation / beating the house"
    )
    guaranteed: bool = Field(default=False, description="Claims guaranteed / risk-free")
    claim_quotes: list[str] = Field(
        default_factory=list, description="Verbatim promotional quotes backing the claims"
    )


class StrategyClaim(BaseModel):
    """A strategy discovered online, with its source and claimed performance."""

    name: str
    game: str | None = None
    source_url: str
    source_title: str | None = None
    claimed: ClaimedMetrics = Field(default_factory=ClaimedMetrics)
    captured_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    notes: list[str] = Field(default_factory=list)


class ClaimsLedgerEntry(BaseModel):
    """A claim joined to what we measured for it (once backtested)."""

    claim: StrategyClaim
    spec_version: int | None = None
    measured_ev_per_unit: float | None = None
    measured_session_win_rate: float | None = None
    measured_risk_of_ruin: float | None = None
    verdict: str = "unverified"


def verdict_for(claim: StrategyClaim, ev_per_unit: float | None) -> str:
    """Plain-language verdict from the measured EV vs. the claim."""
    if ev_per_unit is None:
        return "unverified — not yet backtested"
    if ev_per_unit >= 0:
        return f"measured POSITIVE EV ({ev_per_unit:+.2%}/unit) — investigate carefully"
    hyped = (
        claim.claimed.beats_house_edge
        or claim.claimed.guaranteed
        or (claim.claimed.win_rate or 0) >= 0.6
    )
    tag = "hyped as a winner but " if hyped else ""
    return f"{tag}measured NEGATIVE EV ({ev_per_unit:+.2%}/unit) — loses to the house edge"


def save_claim(entry: ClaimsLedgerEntry, claims_dir: Path = DEFAULT_CLAIMS_DIR) -> Path:
    claims_dir.mkdir(parents=True, exist_ok=True)
    slug = entry.claim.name.lower().replace(" ", "-").replace("/", "-")
    path = claims_dir / f"claim-{slug}.json"
    path.write_text(entry.model_dump_json(indent=2))
    return path


def load_claims(claims_dir: Path = DEFAULT_CLAIMS_DIR) -> list[ClaimsLedgerEntry]:
    if not claims_dir.exists():
        return []
    return [
        ClaimsLedgerEntry.model_validate_json(p.read_text())
        for p in sorted(claims_dir.glob("claim-*.json"))
    ]


def render_scoreboard(entries: list[ClaimsLedgerEntry]) -> str:
    lines = [
        "# CasinoAI Claims Scoreboard (Phase 8)",
        "",
        "Strategies discovered online: what the promoter **claims** vs. what the "
        "pipeline **measured**. Every strategy is run through the same "
        "extract → review → backtest path as the PDF library.",
        "",
        "| Strategy | Game | Claimed | Measured EV/unit | Verdict |",
        "|---|---|---|---|---|",
    ]
    for e in entries:
        c = e.claim.claimed
        claimed = []
        if c.win_rate is not None:
            claimed.append(f"{c.win_rate:.0%} win")
        if c.dollars_per_day:
            claimed.append(f"${c.dollars_per_day:,.0f}/day")
        if c.dollars_per_hour:
            claimed.append(f"${c.dollars_per_hour:,.0f}/hr")
        if c.beats_house_edge:
            claimed.append("beats house")
        if c.guaranteed:
            claimed.append("guaranteed")
        claimed_s = ", ".join(claimed) or "—"
        ev = f"{e.measured_ev_per_unit:+.2%}" if e.measured_ev_per_unit is not None else "—"
        verdict = (
            "loses"
            if (e.measured_ev_per_unit or 0) < 0
            else ("unverified" if e.measured_ev_per_unit is None else "POSITIVE?")
        )
        lines.append(
            f"| [{e.claim.name}]({e.claim.source_url}) | {e.claim.game or '—'} | "
            f"{claimed_s} | {ev} | {verdict} |"
        )
    lines += ["", f"_{len(entries)} discovered strategies tested._"]
    return "\n".join(lines)
