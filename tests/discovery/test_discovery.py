"""Phase 8 discovery: ingest → claims ledger → scoreboard."""

from casinoai.discovery import (
    ClaimedMetrics,
    ClaimsLedgerEntry,
    StrategyClaim,
    ingest_text,
    load_claims,
    render_scoreboard,
    save_claim,
    verdict_for,
)
from casinoai.parsing.parser import ParsedDoc


def test_ingest_text_produces_parsed_doc(tmp_path):
    doc = ingest_text(
        "Guaranteed Roulette Winner",
        "Bet red. Double after every loss. You cannot lose!",
        "https://example.com/system",
        cache_dir=tmp_path,
    )
    assert doc.parser == "web-ingest"
    assert doc.source_path == "https://example.com/system"
    md = list(tmp_path.glob("*.md"))[0].read_text()
    assert "Source: https://example.com/system" in md
    assert "Double after every loss" in md
    # sidecar round-trips as a ParsedDoc (feeds `casinoai extract`)
    sidecar = list(tmp_path.glob("*.json"))[0]
    assert ParsedDoc.model_validate_json(sidecar.read_text()) == doc


def test_ingest_is_content_hashed(tmp_path):
    a = ingest_text("S", "same text", "u1", cache_dir=tmp_path)
    b = ingest_text("S", "same text", "u2", cache_dir=tmp_path)
    assert a.sha256 == b.sha256


def _claim(name, **claimed):
    return StrategyClaim(
        name=name,
        game="roulette",
        source_url=f"https://x.com/{name}",
        claimed=ClaimedMetrics(**claimed),
    )


def test_verdict_language():
    hyped = _claim("Sure Thing", win_rate=0.9, guaranteed=True)
    assert "loses to the house edge" in verdict_for(hyped, -0.027)
    assert "hyped as a winner" in verdict_for(hyped, -0.027)
    assert "unverified" in verdict_for(hyped, None)
    assert "POSITIVE" in verdict_for(hyped, 0.01)


def test_claims_ledger_save_load_and_scoreboard(tmp_path):
    e1 = ClaimsLedgerEntry(
        claim=_claim("Money Maker", win_rate=0.85, dollars_per_day=3000, beats_house_edge=True),
        spec_version=1,
        measured_ev_per_unit=-0.021,
        verdict="loses",
    )
    e2 = ClaimsLedgerEntry(claim=_claim("Untested System"))
    save_claim(e1, claims_dir=tmp_path)
    save_claim(e2, claims_dir=tmp_path)
    loaded = load_claims(tmp_path)
    assert len(loaded) == 2

    md = render_scoreboard(loaded)
    assert "Money Maker" in md
    assert "85% win" in md
    assert "$3,000/day" in md
    assert "-2.10%" in md
    assert "2 discovered strategies tested" in md
