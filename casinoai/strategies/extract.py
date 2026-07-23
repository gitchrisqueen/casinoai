"""LLM extraction: parsed strategy markdown → StrategySpec (H1).

Two-pass, per PLAN.md: extract, then a verification pass where the model
re-reads the source against the drafted spec and flags mismatches. All
uncertainty lands in `ambiguities[]` — never silently guessed.
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from casinoai.llm import complete
from casinoai.parsing import ParsedDoc
from casinoai.strategies.spec import ExtractionResult, SourceRef, StrategySpec

DEFAULT_SPEC_DIR = Path("data/specs")

EXTRACT_SYSTEM = """\
You extract casino betting strategies from books into a machine-executable spec.

Rules:
- Capture exactly what the source prescribes: game, bets, entry conditions,
  betting progression, bankroll and stop rules, and what state the player tracks.
- Prefer the structured condition/progression kinds; use kind="custom" only when
  the strategy genuinely cannot be expressed with them.
- NEVER guess. If the source is unclear, contradictory, or leaves a rule
  undefined, record it verbatim-ish in `ambiguities` for a human reviewer.
- `assumptions` is for things the source clearly implies but never states.
- Ignore marketing filler, testimonials, and win-rate claims; extract only the
  playable rules of the strategy.
- Some systems apply one progression across several games. Set `game` to the
  primary game (the one described in most detail), list the rest in
  `also_applicable_to`, and express the bets in the primary game's terms.
"""

VERIFY_SYSTEM = """\
You are auditing a strategy spec that was extracted from a casino strategy book.
Compare the spec against the source text. Report every place the spec:
- contradicts the source,
- invents a rule the source does not state,
- or omits a rule the source does state.
Be precise and cite the source wording. An empty list means the spec is faithful.
"""


class VerificationReport(BaseModel):
    faithful: bool = Field(description="True if the spec matches the source with no issues")
    issues: list[str] = Field(default_factory=list)


def extract_strategy(
    parsed: ParsedDoc,
    model: str | None = None,
    verify: bool = True,
) -> ExtractionResult:
    """Extract a StrategySpec from a parsed document; verification issues are
    appended to the spec's ambiguities so the human review gate sees them."""
    markdown = Path(parsed.markdown_path).read_text()

    result = complete(
        f"Extract the betting strategy from this book:\n\n{markdown}",
        model=model,
        system=EXTRACT_SYSTEM,
        schema=ExtractionResult,
        tag=f"extract:{Path(parsed.source_path).stem}",
    )
    extraction: ExtractionResult = result.parsed
    extraction.spec.source = SourceRef(
        pdf_path=parsed.source_path, sha256=parsed.sha256, parser=parsed.parser
    )
    extraction.spec.approval = None  # only the human review gate sets this

    if verify:
        spec_yaml = yaml.safe_dump(extraction.spec.model_dump(mode="json"), sort_keys=False)
        verification = complete(
            f"SPEC:\n{spec_yaml}\n\nSOURCE:\n{markdown}",
            model=model,
            system=VERIFY_SYSTEM,
            schema=VerificationReport,
            tag=f"verify:{Path(parsed.source_path).stem}",
        )
        report: VerificationReport = verification.parsed
        extraction.spec.ambiguities.extend(f"[verifier] {issue}" for issue in report.issues)

    return extraction


def save_spec(spec: StrategySpec, spec_dir: Path = DEFAULT_SPEC_DIR) -> Path:
    """Write a draft spec (pre-approval) as YAML; returns the path."""
    spec_dir.mkdir(parents=True, exist_ok=True)
    slug = spec.name.lower().replace(" ", "-")
    path = spec_dir / f"{slug}.yaml"
    path.write_text(yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False))
    return path


def load_spec(path: Path) -> StrategySpec:
    return StrategySpec.model_validate(yaml.safe_load(Path(path).read_text()))
