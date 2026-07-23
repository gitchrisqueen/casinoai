"""CasinoAI command-line entry point.

Subcommands land as their phases do (see PLAN.md):
parse, extract, review, conform, backtest.
"""

import argparse
import sys
from pathlib import Path


def _cmd_parse(args: argparse.Namespace) -> int:
    from casinoai.parsing import parse_pdf

    target = Path(args.path)
    pdfs = sorted(target.rglob("*.pdf")) if target.is_dir() else [target]
    if not pdfs:
        print(f"No PDFs found under {target}", file=sys.stderr)
        return 1
    for pdf in pdfs:
        doc = parse_pdf(pdf, parser=args.parser, force=args.force)
        print(f"{pdf} -> {doc.markdown_path} [{doc.parser}, {doc.n_chars} chars]")
    return 0


def _cmd_extract(args: argparse.Namespace) -> int:
    from casinoai.parsing import ParsedDoc, parse_pdf
    from casinoai.strategies import extract_strategy, save_spec

    path = Path(args.path)
    if path.suffix == ".json":
        parsed = ParsedDoc.model_validate_json(path.read_text())
    else:
        parsed = parse_pdf(path)
    result = extract_strategy(parsed, model=args.model, verify=not args.no_verify)
    spec_path = save_spec(result.spec)
    print(f"Spec: {spec_path}")
    print(f"  game: {result.spec.game}  bets: {[b.bet_type for b in result.spec.bets]}")
    print(f"  progression: {result.spec.progression.kind}")
    if result.spec.ambiguities:
        print(f"  ambiguities ({len(result.spec.ambiguities)}) — needs human review:")
        for a in result.spec.ambiguities:
            print(f"    - {a}")
    for note in result.extraction_notes:
        print(f"  note: {note}")
    return 0


def _cmd_review(args: argparse.Namespace) -> int:
    from casinoai.strategies import load_spec
    from casinoai.strategies.review import render_spec, review_interactive

    spec = load_spec(Path(args.spec))
    if args.show:
        print(render_spec(spec))
        return 0
    return review_interactive(spec)


def _cmd_backtest(args: argparse.Namespace) -> int:
    from casinoai.backtest.runner import backtest, save_summary
    from casinoai.strategies import load_spec

    spec = load_spec(Path(args.spec))
    summary = backtest(spec, seeds=list(range(args.seeds)), max_rounds=args.rounds)
    path = save_summary(summary)
    print(f"Backtest: {summary.strategy} v{summary.spec_version} [{summary.game}]")
    print(f"  sessions: {summary.n_sessions}  rounds: {summary.total_rounds:,}")
    print(f"  EV/unit staked: {summary.ev_per_unit_staked:+.4%}")
    print(f"  session win rate: {summary.session_win_rate:.1%}")
    mean, sd = summary.mean_session_net, summary.stdev_session_net
    print(f"  mean session net: {mean:+.1f}u  (σ {sd:.1f}u)")
    dd, ruin = summary.worst_drawdown_units, summary.risk_of_ruin
    print(f"  worst drawdown: {dd:.1f}u  risk of ruin: {ruin:.1%}")
    print(f"  saved -> {path}")
    return 0


def _cmd_conform(args: argparse.Namespace) -> int:
    from casinoai.harness.conformance import run_conformance
    from casinoai.strategies import load_spec

    spec = load_spec(Path(args.spec))
    report = run_conformance(spec, model=args.model, rounds=args.rounds, seed=args.seed)
    results_dir = Path("data/results")
    results_dir.mkdir(parents=True, exist_ok=True)
    slug = report.strategy.lower().replace(" ", "-")
    model_slug = report.model.replace("/", "_").replace(":", "_")
    out = results_dir / f"conformance-{slug}-v{report.spec_version}-{model_slug}.json"
    out.write_text(report.model_dump_json(indent=2))
    print(f"Conformance: {report.strategy} v{report.spec_version} × {report.model}")
    print(f"  decisions: {report.decisions}  matches: {report.matches}")
    print(f"  match rate: {report.match_rate:.2%}  cost: ${report.total_cost_usd:.4f}")
    for d in report.divergences[:10]:
        print(f"  ✗ round {d.round_index}: expected {d.expected} got {d.actual} — {d.rationale}")
    if len(report.divergences) > 10:
        print(f"  ... and {len(report.divergences) - 10} more divergences")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    from casinoai.reports.leaderboard import (
        build_leaderboard,
        load_backtests,
        render_markdown,
        write_report,
    )

    summaries = load_backtests()
    if not summaries:
        print("No backtest results in data/results/ — run `casinoai backtest` first.")
        return 1
    rows = build_leaderboard(summaries)
    print(render_markdown(rows))
    path = write_report()
    print(f"\nsaved -> {path}")

    from casinoai.reports import conformance_matrix

    conf_reports = conformance_matrix.load_conformance()
    if conf_reports:
        print()
        print(conformance_matrix.render_markdown(conf_reports))
        conf_path = conformance_matrix.write_report()
        print(f"\nsaved -> {conf_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="casinoai",
        description="Systemized testing of casino betting strategies.",
    )
    sub = parser.add_subparsers(dest="command")

    p_parse = sub.add_parser("parse", help="Parse PDF(s) to cached markdown in data/parsed/")
    p_parse.add_argument("path", help="A PDF file or a directory to scan recursively")
    p_parse.add_argument("--parser", choices=["docling", "pymupdf4llm"], default=None)
    p_parse.add_argument("--force", action="store_true", help="Re-parse even if cached")
    p_parse.set_defaults(func=_cmd_parse)

    p_extract = sub.add_parser("extract", help="Extract a StrategySpec from a parsed doc or PDF")
    p_extract.add_argument("path", help="A parsed-doc .json sidecar or a PDF (parsed on demand)")
    p_extract.add_argument("--model", default=None, help="LLM model id (default from env)")
    p_extract.add_argument("--no-verify", action="store_true", help="Skip the verification pass")
    p_extract.set_defaults(func=_cmd_extract)

    p_review = sub.add_parser("review", help="Human approval gate for a draft spec")
    p_review.add_argument("spec", help="Path to a draft spec YAML (data/specs/...)")
    p_review.add_argument("--show", action="store_true", help="Display only, no approval prompt")
    p_review.set_defaults(func=_cmd_review)

    p_conform = sub.add_parser("conform", help="H2 conformance run: LLM agent vs. oracle")
    p_conform.add_argument("spec", help="Path to a spec YAML")
    p_conform.add_argument("--model", default=None, help="LLM model id (default from env)")
    p_conform.add_argument("--rounds", type=int, default=100)
    p_conform.add_argument("--seed", type=int, default=0)
    p_conform.set_defaults(func=_cmd_conform)

    p_backtest = sub.add_parser("backtest", help="Monte Carlo backtest of an approved spec")
    p_backtest.add_argument("spec", help="Path to a spec YAML (strategies/approved/...)")
    p_backtest.add_argument("--rounds", type=int, default=10_000, help="Max rounds per session")
    p_backtest.add_argument("--seeds", type=int, default=30, help="Number of seeded sessions")
    p_backtest.set_defaults(func=_cmd_backtest)

    p_report = sub.add_parser("report", help="Cross-strategy leaderboard from backtest results")
    p_report.set_defaults(func=_cmd_report)

    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
