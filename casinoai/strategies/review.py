"""Human review gate: draft spec → approved spec (H1's quality bar).

Approved specs are immutable once used in a published run — approving writes
`strategies/approved/<slug>-v<N>.yaml` and refuses to overwrite an existing
version (bump the version instead).
"""

import getpass
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from casinoai.strategies.spec import ApprovalRecord, StrategySpec

APPROVED_DIR = Path("strategies/approved")


def render_spec(spec: StrategySpec) -> str:
    lines = [
        f"Strategy: {spec.name}  (v{spec.version})",
        f"Game:     {spec.game.value}",
        f"Summary:  {spec.summary}",
        f"Bets:     {', '.join(b.bet_type for b in spec.bets) or '(none!)'}",
        f"Progression: {spec.progression.kind}",
        f"Bankroll: {spec.bankroll.model_dump(exclude_none=True)}",
    ]
    if spec.source:
        lines.append(f"Source:   {spec.source.pdf_path} [{spec.source.sha256[:8]}]")
    for label, items in (
        ("State tracked", spec.state_tracked),
        ("Assumptions", spec.assumptions),
        ("AMBIGUITIES", spec.ambiguities),
    ):
        if items:
            lines.append(f"{label} ({len(items)}):")
            lines.extend(f"  - {item}" for item in items)
    return "\n".join(lines)


def approve_spec(
    spec: StrategySpec,
    approved_by: str,
    annotations: list[str],
    approved_dir: Path = APPROVED_DIR,
) -> Path:
    """Stamp the approval and write the immutable approved YAML."""
    slug = spec.name.lower().replace(" ", "-")
    path = approved_dir / f"{slug}-v{spec.version}.yaml"
    if path.exists():
        raise FileExistsError(
            f"{path} already exists — approved specs are immutable; bump the version"
        )
    spec.approval = ApprovalRecord(
        approved_by=approved_by,
        approved_at=datetime.now(UTC).isoformat(),
        annotations=annotations,
    )
    approved_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False))
    return path


def review_interactive(spec: StrategySpec) -> int:
    """Terminal review session; returns process exit code."""
    print(render_spec(spec))
    print()
    if spec.ambiguities:
        print(f"⚠ {len(spec.ambiguities)} ambiguities need resolution before this spec is usable.")
    while True:
        choice = input("[a]pprove / a[n]notate / [q]uit without approving? ").strip().lower()
        annotations: list[str] = []
        if choice == "n":
            print("Enter annotations, one per line (blank line to finish):")
            while line := sys.stdin.readline().strip():
                annotations.append(line)
            continue_choice = input("[a]pprove with these annotations / [q]uit? ").strip().lower()
            if continue_choice != "a":
                return 1
            choice = "a"
        if choice == "a":
            path = approve_spec(spec, approved_by=getpass.getuser(), annotations=annotations)
            print(f"Approved -> {path}")
            return 0
        if choice == "q":
            print("Not approved.")
            return 1
