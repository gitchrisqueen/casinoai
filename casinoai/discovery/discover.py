"""Extract a strategy's *claimed* performance from discovered web text (Phase 8).

The web search itself (finding candidate strategies) is done with the research
tools — Perplexity / web search — and the page text handed here. This module
turns that text into a structured StrategyClaim (the marketing numbers to test)
via the LLM gateway. The strategy's *rules* are extracted separately by the
existing `casinoai extract` path after `ingest_text`.
"""

from casinoai.discovery.claims import ClaimedMetrics, StrategyClaim
from casinoai.llm import complete

CLAIM_SYSTEM = """\
You read a promotional page for a casino betting system and extract ONLY the
performance CLAIMS the promoter makes — not your opinion of them. Capture the
claimed win rate, dollars per hour/day, whether it claims to beat the house edge
or be guaranteed/risk-free, and the verbatim quotes that back those claims. If a
figure is not claimed, leave it null. Do not infer or soften; record the hype
exactly as stated.
"""


def extract_claim(
    name: str,
    text: str,
    source_url: str,
    game: str | None = None,
    source_title: str | None = None,
    model: str | None = None,
) -> tuple[StrategyClaim, float]:
    """Extract the promoter's claims from page text; returns (claim, cost_usd)."""
    result = complete(
        f"Extract the performance claims from this betting-system page:\n\n{text}",
        model=model,
        system=CLAIM_SYSTEM,
        schema=ClaimedMetrics,
        tag=f"discover-claim:{name}",
    )
    claim = StrategyClaim(
        name=name,
        game=game,
        source_url=source_url,
        source_title=source_title,
        claimed=result.parsed,
    )
    return claim, result.cost_usd
